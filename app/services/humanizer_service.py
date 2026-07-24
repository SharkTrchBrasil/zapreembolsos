import random
import asyncio
from app.services.wuzapi_service import wuzapi_client

_TYPING_FLOOR_MS = 700
_TYPING_CEIL_MS = 3000

def calculate_typing_delay(text_length: int) -> float:
    """Calcula o tempo de digitação (delay humanizado) em segundos baseado no tamanho do texto."""
    if text_length == 0:
        return 0.0

    chars_per_minute = random.randint(180, 250)
    chars_per_second = chars_per_minute / 60.0
    
    # Adiciona um tempo de "pensamento" (reading/thinking delay)
    thinking_ms = random.randint(300, 1500)
    
    typing_ms = (text_length / chars_per_second) * 1000
    
    total_ms = thinking_ms + typing_ms
    
    clamped_ms = max(_TYPING_FLOOR_MS, min(total_ms, _TYPING_CEIL_MS))
    return clamped_ms / 1000.0

async def send_humanized_message(phone: str, text: str, skip_delay: bool = False):
    """Envia uma mensagem simulando digitação humana."""
    if skip_delay:
        await wuzapi_client.send_text_message(phone, text)
        return

    # 1. Envia indicador de digitando
    await wuzapi_client.send_typing_indicator(phone, is_typing=True)
    
    # 2. Aguarda o tempo calculado
    delay = calculate_typing_delay(len(text))
    await asyncio.sleep(delay)
    
    # 3. Pausa a digitação
    await wuzapi_client.send_typing_indicator(phone, is_typing=False)
    
    # 4. Envia a mensagem real
    await wuzapi_client.send_text_message(phone, text)
