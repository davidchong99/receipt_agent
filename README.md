# receipt_agent


https://github.com/user-attachments/assets/644dd73e-1945-413f-8208-63fc87e668a9


An AI agent that reads Danish receipts and extracts the shop name, address, CVR number, total amount and moms (VAT) from the receipt. It comes with a small Gradio web app. User can drop or upload a receipt photo and the extracted dat will appear next to it.

When something is not printed on the receipt or it is not readable, the agent looks it up instead of guessing: CVR numbers it has seen before are recalled from a local vector database and anything still missing is searched for on the web.

## How it works
A Lanfchain agent sends the receipt image to a vision-capable model on [OpenRouter](https://openrouter.ai) and returns the result as a structured `Receipt` object (a Pydantic model). The agent is connected to 2 MCP servers:

- **Tavily** (hosted over streamable HTTP) for web search. Only the `tavily_search` tool is exposed to the agent.
- **Qdrant** ([`mcp-server-qdrant`](https://github.com/qdrant/mcp-server-qdrant)), started locally with `uvx`) as a local knowledge base of shop name - CVR pairs. It is stored on disk in `memory/qdrant`, in the `knowledge` collection.

Each lookup follows a fixed order and the results indicates the source of the data:

| Field    | Lookup order                       | Source values                                    |
|----------|------------------------------------|--------------------------------------------------|
| Address  | receipt -> web search              | `receipt`, `web_search`, `not_found`             |
| CVR      | receipt -> vector db -> web search | `receipt`, `vectordb`, `web_search`, `not_found` |

Whenever a CVR is read from a receipt or found on the web, the shop name and CVR are saved to the vector DB, so the next receipt from the same shop won't need a web search.

This agent uses langchain[mcp] libray v1.4.4 and fastmcp.client.group for multiple MCP servers setup.
Langsmith is integrated for tracing and debug.

## Testing

This agent is tested with the following Openrouter LLM models:

| Model                            | Observation          |
|----------------------------------|----------------------|
| `openai/gpt-6-luna`              | Functional           |
| `nex-agi/nex-n2.5-pro`           | Functional           |
| `anthropic/claude-haiku-5.5`     | Functional           |
| `inclusionai/ling-3.0-flash-vl`  | Partially functional |
| `mistralai/mistral-medium-3-5`   | Partially functional |

Some sample receipts are provided in `sample_receipts/`

## Requirements

- Python 3.13 or newer
- uv package manager
- [Openrouter](https://openrouter.ai) API key
- [Tavily](https://tavily.com) API key
- [Langsmith](https://smith.langchain.com) API key

## Setup

```bash
git clone git@github.com:davidchong99/receipt_agent.git
cd receipt_agent
uv sync
cp .env.example .env
```

Then fill in your API keys in ".env"

| Variable             | Required | Description                                                                  |
| -------------------- | -------- |------------------------------------------------------------------------------|
| `OPENROUTER_API_KEY` | yes      | Your OpenRouter API key                                                      |
| `TAVILY_API_KEY`     | yes      | Your Tavily API key                                                          |
| `LANGSMITH_API_KEY`  | yes      | Your Langsmith API key                                                       |
| `OPENROUTER_MODEL`   | no       | Model to use. Defaults to `openai/gpt-6-luna`. It must accept image input.   |

`.env.example` also listed a few models (commented out) that were tested with this agent.

## Usage

### Web app

```bash
uv run app.py
```

Gradio starts a local server and opens it in your browser at http://127.0.0.1:7860.
The extraction might not happen instantly due to the latency in Openrouter API call.

### Inspecting the vector DB

To see which shops and CVR numbers saved by the agent:

```bash
cd utility
uv run python view_vectordb.py
```
The script uses the relative path `../memory/qdrant`, so it has to be run from inside `utility/`.

### Limitations
- The prompt is written for Danish receipts. This agent might not work well with receipts from other countries or languages

