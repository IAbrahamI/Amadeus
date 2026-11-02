"""Amadeus tenant extension: each API key maps to its own PostgreSQL schema.

Config (env):
  HINDSIGHT_API_TENANT_EXTENSION=amadeus_ext.keymap:KeyMapTenantExtension
  HINDSIGHT_API_TENANT_KEYS={"<key>": "amadeus", ...}  (key -> its own database schema)
Requests without a known key are rejected, on HTTP and MCP alike.
"""
import json

from hindsight_api.extensions.tenant import AuthenticationError, Tenant, TenantContext, TenantExtension
from hindsight_api.models import RequestContext


class KeyMapTenantExtension(TenantExtension):
    def __init__(self, config: dict[str, str]):
        super().__init__(config)
        raw = config.get("keys")
        if not raw:
            raise ValueError("HINDSIGHT_API_TENANT_KEYS is required")
        self.keys: dict[str, str] = json.loads(raw)
        if not self.keys:
            raise ValueError("HINDSIGHT_API_TENANT_KEYS must map at least one key")

    async def on_startup(self) -> None:
        for schema in sorted(set(self.keys.values())):
            if schema != "public":
                await self.context.run_migration(schema)

    async def authenticate(self, context: RequestContext) -> TenantContext:
        key = (context.api_key or "").removeprefix("Bearer ").strip()
        schema = self.keys.get(key)
        if schema is None:
            raise AuthenticationError("Invalid API key")
        return TenantContext(schema_name=schema)

    async def authenticate_mcp(self, context: RequestContext) -> TenantContext:
        return await self.authenticate(context)

    async def list_tenants(self) -> list[Tenant]:
        return [Tenant(schema=s) for s in sorted(set(self.keys.values()))]
