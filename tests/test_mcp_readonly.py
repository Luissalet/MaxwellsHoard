"""Inspecting examples/materials and coarse validation do not store studies."""
import json
import os
import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.mark.anyio
async def test_readonly_helpers_are_declared_and_create_no_data(tmp_path):
    data = tmp_path / 'data'
    params = StdioServerParameters(command=sys.executable, args=['-m', 'maxwell.mcp_server'],
        env={**os.environ, 'MAXWELL_DATA': str(data)})
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = {tool.name: tool for tool in (await session.list_tools()).tools}
            for name in ('maxwell_examples', 'maxwell_materials', 'maxwell_check'):
                assert tools[name].annotations.model_dump(by_alias=True)['readOnlyHint'] is True
            for name in ('maxwell_solve', 'maxwell_compare', 'maxwell_refinement', 'maxwell_design_search'):
                ann = tools[name].annotations
                assert ann is None or ann.model_dump(by_alias=True).get('readOnlyHint') is not True
            async def call(name, arguments):
                result = await session.call_tool(name, arguments)
                assert not result.is_error
                return json.loads(next(block.text for block in result.content if block.type == 'text'))
            example = await call('maxwell_examples', {'example_id': 'bracket'})
            assert await call('maxwell_materials', {})
            assert (await call('maxwell_check', {'problem': example['problem']}))['status'] == 'valid'
    assert not data.exists(), 'Readonly helpers unexpectedly created app data'
