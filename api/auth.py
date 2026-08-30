"""Autenticación de la API — una sola API key de administrador (header X-API-Key), suficiente
para un puñado de operadores internos administrando gateways. Si esto crece a múltiples
usuarios/roles con necesidad de auditoría por persona, migrar a algo con identidad real
(usuarios+contraseña, tokens por persona) — no vale la pena esa complejidad todavía."""
from fastapi import Header, HTTPException, status

from mqtt_agrohub import config


async def requiere_api_key(x_api_key: str = Header(default=None)):
    if not config.ADMIN_API_KEY:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            'ADMIN_API_KEY no está configurada en el servidor — ver .env.example.',
        )
    if x_api_key != config.ADMIN_API_KEY:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, 'API key inválida o ausente (header X-API-Key).')
