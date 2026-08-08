# 验证 local-mic-mcp 连接器：用 mcp stdio 客户端真实拉起 server 并 list_tools + mic_status
# 用法：<venv>/Scripts/python.exe test_client.py
import os, sys, asyncio
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.session import ClientSession

# server.py 与本脚本同目录；如需指定 venv，填 PY 绝对路径，否则用当前 python
SERVER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "server.py")
PY = sys.executable


async def main():
    params = StdioServerParameters(command=PY, args=[SERVER])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("TOOLS:", [t.name for t in tools.tools])
            res = await session.call_tool("mic_status", {})
            print("mic_status ->", res.content[0].text)
            print("STDIO_HANDSHAKE_OK")


asyncio.run(main())
