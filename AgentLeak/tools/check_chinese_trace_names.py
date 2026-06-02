"""Scan Chinese AgentLeak traces and source templates for English privacy names.

Policy:
- ``--path`` scans JSON/JSONL/Markdown/YAML/TXT trace-visible files or directories.
- ``--source`` scans Python/Markdown/YAML/TXT source/template files or directories.
- The scanner is denylist-driven: it flags known privacy-bearing English names,
  entities, and source templates that should have been localized.
- Technical tokens such as model IDs, framework names, schema keys, enum values,
  provider names, and file paths are intentionally ignored when they appear as
  standalone technical values.
"""

import argparse
import json
import pathlib
import re
import sys

DATA_EXTENSIONS = {".json", ".jsonl", ".md", ".yaml", ".yml", ".txt"}
SOURCE_EXTENSIONS = {".py", ".md", ".yaml", ".yml", ".txt"}

PRIVACY_FIELD_TOKENS = {
    "name",
    "person",
    "reference",
    "company",
    "contact",
    "client",
    "patient",
    "customer",
    "employee",
    "candidate",
    "attorney",
    "provider",
    "merchant",
    "location",
    "address",
    "email",
    "phone",
    "ssn",
    "id",
    "card",
    "account",
    "bank",
    "manager",
    "party",
}

PRIVACY_FIELD_CANONICALS = {
    "opposingparty",
    "relationshipmanager",
    "contactperson",
    "emailaddress",
    "phonenumber",
    "bankaccount",
    "cardnumber",
    "accountnumber",
    "postaladdress",
}

DENYLIST_TERMS = [
    "John Smith",
    "Alice Johnson",
    "Bob Williams",
    "John Doe",
    "Jane Doe",
    "Dr. Smith",
    "Smith",
    "Smith 医生",
    "Sophie Martin",
    "Michael Thompson",
    "Carolyn Daniel",
    "James Mayo",
    "Christopher Hale",
    "Brian Mathews",
    "Acme Corp",
    "BetaTech",
]

SOURCE_PATTERNS = [
    (re.compile(r"Patient-"), "source template prefix"),
    (re.compile(r"Customer-"), "source template prefix"),
    (re.compile(r"Relationship Manager: Sophie Martin"), "source template name/entity"),
]

LIKELY_NAME_PATTERN = re.compile(
    r"(?<![A-Za-z0-9/._-])(?:[A-Z][a-z]{1,30}\s+[A-Z][a-z]{1,30})(?![A-Za-z0-9/._-])"
)

LIKELY_NAME_STOPWORDS = {
    "account",
    "analyst",
    "business",
    "chief",
    "customer",
    "director",
    "earnings",
    "engineer",
    "engineering",
    "lead",
    "manager",
    "officer",
    "operations",
    "partner",
    "product",
    "project",
    "quality",
    "relationship",
    "sales",
    "service",
    "specialist",
    "support",
    "technical",
    "team",
}

SENTENCE_CUE_PATTERN = re.compile(
    r"\b(?:"
    r"called|contact|draft|message|note|output|provide|quoted|request|requested|requests|review|reviewed|say|said|send|show|share|shared|tell|told|vault"
    r")\b",
    re.IGNORECASE,
)

TECHNICAL_VALUE_PATTERNS = [
    re.compile(r"(?:openai/)?gpt-[\w.-]+", re.IGNORECASE),
    re.compile(r"(?:anthropic/)?claude-[\w.-]+", re.IGNORECASE),
    re.compile(r"(?:google/)?gemini[\w./-]*", re.IGNORECASE),
    re.compile(r"CrewAI", re.IGNORECASE),
    re.compile(r"LangChain", re.IGNORECASE),
    re.compile(r"AutoGPT", re.IGNORECASE),
    re.compile(r"MetaGPT", re.IGNORECASE),
    re.compile(r"JSON", re.IGNORECASE),
    re.compile(r"API", re.IGNORECASE),
    re.compile(r"LLM", re.IGNORECASE),
    re.compile(r"HTTP", re.IGNORECASE),
    re.compile(r"SSL", re.IGNORECASE),
    re.compile(r"SSN", re.IGNORECASE),
    re.compile(r"CANARY_[A-Z0-9_]+"),
    re.compile(r"C[1-6]"),
    re.compile(r"openai", re.IGNORECASE),
    re.compile(r"anthropic", re.IGNORECASE),
    re.compile(r"google", re.IGNORECASE),
    re.compile(r"azure", re.IGNORECASE),
    re.compile(r"mistral", re.IGNORECASE),
    re.compile(r"cohere", re.IGNORECASE),
    re.compile(r"replicate", re.IGNORECASE),
    re.compile(r"dashscope", re.IGNORECASE),
    re.compile(r"openrouter", re.IGNORECASE),
]

URL_OR_PATH_RULES = [
    re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://\S+$"),
    re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\|/|\.\.?[\\/])\S*$"),
]


def boundary_pattern(text: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![A-Za-z]){re.escape(text)}(?![A-Za-z])")


def build_rules() -> list[tuple[re.Pattern[str], str]]:
    rules: list[tuple[re.Pattern[str], str]] = []
    for term in DENYLIST_TERMS:
        rules.append((boundary_pattern(term), "denylisted exact privacy-bearing name/entity"))
    for pattern, reason in SOURCE_PATTERNS:
        rules.append((pattern, reason))
    return rules


DENYLIST_RULES = build_rules()


def normalize_key(text: str) -> str:
    return "".join(re.findall(r"[a-z0-9]+", text.lower()))


def is_privacy_bearing_key(text: str) -> bool:
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    if not tokens:
        return False
    if normalize_key(text) in PRIVACY_FIELD_CANONICALS:
        return True
    return any(token in PRIVACY_FIELD_TOKENS for token in tokens)


def likely_name_matches(text: str, require_sentence_context: bool = False) -> list[str]:
    matches: list[str] = []
    for match in LIKELY_NAME_PATTERN.finditer(text):
        candidate = match.group(0)
        first_word, second_word = candidate.split()
        if first_word.lower() in LIKELY_NAME_STOPWORDS or second_word.lower() in LIKELY_NAME_STOPWORDS:
            continue
        if require_sentence_context:
            context = f"{text[:match.start()]} {text[match.end():]}"
            if not SENTENCE_CUE_PATTERN.search(context):
                continue
        matches.append(candidate)
    return matches


def quoted_segments(text: str) -> list[str]:
    segments: list[str] = []
    for match in re.finditer(r'"([^"\n]{1,300})"|\'([^\'\n]{1,300})\'', text):
        segment = match.group(1) if match.group(1) is not None else match.group(2)
        if segment:
            segments.append(segment)
    return segments


def is_technical_value(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    for pattern in URL_OR_PATH_RULES:
        if pattern.fullmatch(stripped):
            return True
    for pattern in TECHNICAL_VALUE_PATTERNS:
        if pattern.fullmatch(stripped):
            return True
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*\.(?:json|jsonl|md|markdown|yaml|yml|py|txt)", stripped):
        return True
    return False


def overlaps(span: tuple[int, int], spans: list[tuple[int, int]]) -> bool:
    for start, end in spans:
        if span[0] < end and start < span[1]:
            return True
    return False


def collect_matches(text: str, patterns: list[tuple[re.Pattern[str], str]]) -> list[tuple[str, str]]:
    matches: list[tuple[str, str]] = []
    seen_spans: list[tuple[int, int]] = []
    for pattern, reason in patterns:
        for match in pattern.finditer(text):
            span = match.span()
            if overlaps(span, seen_spans):
                continue
            seen_spans.append(span)
            matches.append((match.group(0), reason))
    return matches


def iter_files(paths: list[str], allowed_extensions: set[str]) -> list[pathlib.Path]:
    files: list[pathlib.Path] = []
    for root in paths:
        current = pathlib.Path(root)
        if not current.exists():
            raise FileNotFoundError(root)
        if current.is_file():
            if current.suffix.lower() in allowed_extensions:
                files.append(current)
            continue
        for path in current.rglob("*"):
            if path.is_file() and path.suffix.lower() in allowed_extensions:
                files.append(path)
    return files


def scan_json_value(
    value: object,
    location: str,
    findings: list[tuple[str, str, str, str]],
    privacy_context: bool = False,
) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            next_location = f"{location}.{key}" if location else str(key)
            scan_json_value(item, next_location, findings, privacy_context or is_privacy_bearing_key(str(key)))
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            next_location = f"{location}[{index}]" if location else f"[{index}]"
            scan_json_value(item, next_location, findings, privacy_context)
        return
    if isinstance(value, str):
        if is_technical_value(value):
            return
        for offending_value, reason in collect_matches(value, DENYLIST_RULES):
            findings.append((location or "root", offending_value, reason, value))
        if privacy_context:
            for offending_value in likely_name_matches(value):
                findings.append((location or "root", offending_value, "likely personal name in privacy-bearing field", value))


def scan_json_file(path: pathlib.Path) -> list[tuple[str, str, str, str]]:
    findings: list[tuple[str, str, str, str]] = []
    if path.suffix.lower() == ".jsonl":
        for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not raw_line.strip():
                continue
            data = json.loads(raw_line)
            scan_json_value(data, f"line {line_number}", findings)
        return findings
    data = json.loads(path.read_text(encoding="utf-8"))
    scan_json_value(data, "", findings)
    return findings


def scan_text_file(path: pathlib.Path) -> list[tuple[str, str, str, str]]:
    findings: list[tuple[str, str, str, str]] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped or is_technical_value(stripped):
            continue
        for offending_value, reason in collect_matches(raw_line, DENYLIST_RULES):
            findings.append((f"line {line_number}", offending_value, reason, raw_line))
        for segment in quoted_segments(raw_line):
            for offending_value in likely_name_matches(segment, require_sentence_context=True):
                findings.append((f"line {line_number}", offending_value, "likely personal name in quoted source text", raw_line))
    return findings


def scan_paths(paths: list[str]) -> tuple[list[tuple[str, str, str, str]], int]:
    files = iter_files(paths, DATA_EXTENSIONS)
    findings: list[tuple[str, str, str, str]] = []
    scanned_files = 0
    for path in files:
        scanned_files += 1
        if path.suffix.lower() in {".json", ".jsonl"}:
            path_findings = scan_json_file(path)
        else:
            path_findings = scan_text_file(path)
        findings.extend((str(path), location, offending_value, reason) for location, offending_value, reason, _ in path_findings)
    return findings, scanned_files


def scan_sources(paths: list[str]) -> tuple[list[tuple[str, str, str, str]], int]:
    files = iter_files(paths, SOURCE_EXTENSIONS)
    findings: list[tuple[str, str, str, str]] = []
    scanned_files = 0
    for path in files:
        scanned_files += 1
        path_findings = scan_text_file(path)
        findings.extend((str(path), location, offending_value, reason) for location, offending_value, reason, _ in path_findings)
    return findings, scanned_files


def print_findings(findings: list[tuple[str, str, str, str]]) -> None:
    for file_path, location, offending_value, reason in findings:
        print(f"VIOLATION: {file_path} | {location} | {offending_value} | {reason}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan Chinese AgentLeak traces for English privacy-bearing names.")
    parser.add_argument("--path", action="append", default=[], help="Recursively scan data files or directories")
    parser.add_argument("--source", action="append", default=[], help="Recursively scan source/template files or directories")
    args = parser.parse_args()

    if not args.path and not args.source:
        parser.print_help()
        return 0

    try:
        findings: list[tuple[str, str, str, str]] = []
        scanned_files = 0
        if args.path:
            path_findings, path_scanned = scan_paths(args.path)
            findings.extend(path_findings)
            scanned_files += path_scanned
        if args.source:
            source_findings, source_scanned = scan_sources(args.source)
            findings.extend(source_findings)
            scanned_files += source_scanned
    except FileNotFoundError as error:
        print(f"ERROR: input path not found: {error.args[0]}", file=sys.stderr)
        return 2

    if findings:
        print_findings(findings)

    print(f"SUMMARY: files scanned={scanned_files} violations={len(findings)}")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
