import asyncio
import os
from dotenv import load_dotenv
from browser_use import Agent
from langchain_groq import ChatGroq

load_dotenv()

async def main():
    llm = ChatGroq(
        model="openai/gpt-oss-120b",
        api_key=os.getenv("GROQ_API_KEY"),
    )
    agent = Agent(task="Go to https://example.com and return the title", llm=llm)
    result = await agent.run()
    print("Result:", result)

if __name__ == "__main__":
    asyncio.run(main())
