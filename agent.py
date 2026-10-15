import os
import mimetypes
import base64
from dotenv import load_dotenv
from fastmcp import Client
from fastmcp.client.group import ClientGroup
from fastmcp.client.transports import StdioTransport, StreamableHttpTransport
from langchain_openrouter import ChatOpenRouter
from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_core.messages import HumanMessage
from langchain.mcp import MCPAdapter
from pydantic import BaseModel, Field
from typing import Literal
from pathlib import Path

load_dotenv(override=True)
MODEL = os.getenv("OPENROUTER_MODEL", "openai/gpt-6-luna")

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
if OPENROUTER_API_KEY is None:
    raise RuntimeError("Openrouter api key not found!")

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
if TAVILY_API_KEY is None:
    raise RuntimeError("Tavily api key not found!")

SYSTEM_PROMPT = """You extract data from receipt, most of them in Danish.

Read the receipt image and figure out:
- shop_name: the shop name as printed
- shop_address: address of the shop as printed
- shop_cvr: the Danish CVR company registration ("CVR-NR")
- amount: the total paid as printed in receipt, look for "I ALT", "TOTAL", "AT BETALE", "SUM", "Bon total" or similar.
- moms: the Danish VAT or MOMS as printed in receipt ("MOMS", "HERAF MOMS", "MOMS UDGØR")

Amount rule: 
- The total amount has VAT or mom included. Do not perform any calculation, just take the total as it is.
- Danish receipts use a comma as the decimal separator and a period as the thousand separator. Do not convert or change anything.

Moms rule:
- Danish receipts use a comma as the decimal separator and a period as the thousand separator. Do not convert or change anything.

Address rule:
- If the address is printed on the receipt, use it for shop_address and set the address_source to "receipt". Do not search
- If the address is missing or unreadable, use Tavily search tool to find it. Set address_source to "web_search" when the search return a match.
- If the search tool deos not return a match, leave shop_address empty and set address_source to "not_found"

Shop CVR rule:
- If the CVR is printed on the receipt, use it and set the cvr_source to "receipt" and store the shop_name and shop_cvr into vectordb if they are not in vectordb.
- If the CVR is missing or unreadable, use vectordb to find it. If the CVR is found, set cvr_source to "vectordb".
- If the CVR is not found in vectordb, use Tavily search tool to find it. Set cvr_source to "web_search" when the search return a match and store the shop_name and shop_cvr into vectordb.
- If the search tool deos not return a match, leave shop_cvr empty and set cvr_source to "not_found"

Never guess. If moms is not printed on the receipt, leave it empty.
"""


class Receipt(BaseModel):
    """Data extracted from the receipt"""

    shop_name: str | None = Field(description="Shop name as printed on the receipt")
    shop_address: str | None = Field(
        description="Street, post code and city of the shop"
    )
    shop_cvr: int | None = Field(description="Danish company registration number CVR")
    amount: float | None = Field(description="Total paid, VAT included")
    moms: float | None = Field(description="VAT (moms) printed on the receipt")
    address_source: Literal["receipt", "web_search", "not_found"] = Field(
        description="Where the address comes from"
    )
    cvr_source: Literal["receipt", "web_search", "vectordb", "not_found"] = Field(
        description="Where the CVR comes from"
    )


# local vector database
vectordb_path = Path("memory/qdrant")

# MCP server for web search and vector DB: one independent connection each
mcpGroup = ClientGroup(
    {
        "search": Client(
            StreamableHttpTransport(
                f"https://mcp.tavily.com/mcp/?tavilyApiKey={TAVILY_API_KEY}"
            )
        ),
        "vectordb": Client(
            StdioTransport(
                command="uvx",
                args=["mcp-server-qdrant"],
                env={
                    **os.environ,
                    "QDRANT_LOCAL_PATH": str(vectordb_path),
                    "COLLECTION_NAME": "knowledge",
                },
                keep_alive=True,
            ),
            mode="legacy",
        ),
    }
)


async def filter_search_tool(adaptor: MCPAdapter):
    """Select only search tool from Tavily without affecting other tools"""
    tools = await adaptor.list_tools()
    filtered_tools = [
        t for t in tools if "tavily_search" in t.name or "tavily" not in t.name
    ]
    return filtered_tools


openrouter = ChatOpenRouter(model=MODEL, api_key=OPENROUTER_API_KEY, temperature=0)


def validate_image(path: Path):
    # mime returns a tuple, first item is the type
    mime = mimetypes.guess_type(path)[0]
    if not mime.startswith("image/"):
        raise ValueError(f"{path} is not an image ({mime}); please use JPG or PNG")
    return mime


def image_as_string(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode()


async def extract_data_from_receipt(image: Path) -> Receipt:
    async with MCPAdapter(mcpGroup) as adapter:
        agent = create_agent(
            model=openrouter,
            system_prompt=SYSTEM_PROMPT,
            tools=await filter_search_tool(adapter),
            response_format=ToolStrategy(Receipt),
        )

        message = HumanMessage(
            content=[
                {
                    "type": "text",
                    "text": "Extract the shop name, shop address, CVR, amount and moms from this receipt.",
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{validate_image(image)};base64,{image_as_string(image)}"
                    },
                },
            ]
        )

        result = await agent.ainvoke({"messages": [message]})
        print(result["structured_response"])
        return result["structured_response"]
