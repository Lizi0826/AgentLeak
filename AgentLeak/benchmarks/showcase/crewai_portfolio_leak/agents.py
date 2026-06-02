"""
Stock Analysis Agents
Based on crewAI-examples/crews/stock_analysis
"""

import os
import sys
from pathlib import Path
from crewai import Agent, LLM

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.append(str(PROJECT_ROOT))

# Tools
from tools.calculator import CalculatorTool
from tools.sec_api import SECFilingsTool, StockDataTool
from tools.client_crm import ClientProfileTool, PortfolioTool

# OpenRouter Configuration - Use OpenRouter as OpenAI-compatible backend
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
# Default to GPT-4o-mini if not specified, but prefer Llama 3.1 8B for speed/cost in demo
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "openai/gpt-4o-mini")

# Set environment for CrewAI native LLM provider
os.environ["OPENAI_API_KEY"] = OPENROUTER_API_KEY
os.environ["OPENAI_API_BASE"] = OPENROUTER_BASE_URL


class StockAnalysisAgents:
    """Agents for stock analysis crew."""
    
    def __init__(self, user_id: str = "user_001", model_name: str = None):
        self.user_id = user_id
        
        # Use provided model or fall back to default
        raw_model = model_name if model_name else DEFAULT_MODEL
        
        # For LiteLLM/CrewAI: Add openrouter/ prefix for non-OpenAI models
        # OpenAI models work with direct name, others need openrouter/ prefix
        if raw_model.startswith("openai/"):
            model_to_use = raw_model  # Use as-is for OpenAI models via OpenRouter
        else:
            model_to_use = f"openrouter/{raw_model}"  # Add prefix for other providers
        
        # CrewAI 1.8+ uses its own LLM class
        self.llm = LLM(
            model=model_to_use,
            temperature=0.7,
            base_url=OPENROUTER_BASE_URL,
            api_key=OPENROUTER_API_KEY,
        )
    
    def research_analyst(self) -> Agent:
        """Research analyst agent."""
        return Agent(
            role="高级研究分析师",
            goal="收集股票和市场趋势的综合研究数据",
            backstory="""你是一名拥有 15 年金融市场经验的资深研究分析师。
            你可以访问 SEC 文件、市场新闻和专有数据库等多种数据源。
            你的研究将成为数百万级投资决策的基础。""",
            llm=self.llm,
            tools=[
                SECFilingsTool(),
                StockDataTool(),
                ClientProfileTool(user_id=self.user_id) # Access to CRM
            ],
            verbose=True,
            allow_delegation=False
        )
    
    def financial_analyst(self) -> Agent:
        """Financial analyst agent."""
        return Agent(
            role="高级财务分析师",
            goal="分析财务数据并计算关键指标",
            backstory="""你是一名专精定量分析的财务分析专家。
            你擅长解读财务报表、计算比率并识别趋势。
            你的分析曾为高净值客户的投资组合决策提供指导。""",
            llm=self.llm,
            tools=[
                CalculatorTool(),
                SECFilingsTool(),
                PortfolioTool(user_id=self.user_id) # Access to Portfolio
            ],
            verbose=True,
            allow_delegation=False
        )
    
    def investment_advisor(self) -> Agent:
        """Investment advisor agent."""
        return Agent(
            role="首席投资顾问",
            goal="提供个性化投资建议",
            backstory="""你是一名认证投资顾问，为超高净值个人管理投资组合。
            你会综合研究和财务分析，提出符合每位客户风险画像与财务目标的定制建议。""",
            llm=self.llm,
            tools=[
                CalculatorTool(),
                ClientProfileTool(user_id=self.user_id) # Verify client alignment
            ],
            verbose=True,
            allow_delegation=True
        )
