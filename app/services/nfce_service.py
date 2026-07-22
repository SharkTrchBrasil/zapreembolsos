from PIL import Image
import io
import re
from pyzbar.pyzbar import decode

class NFCeService:
    def decode_qr_from_image_bytes(self, image_bytes: bytes) -> str | None:
        """
        Tenta ler um QR Code da imagem. Retorna a URL se encontrar, ou None.
        """
        try:
            image = Image.open(io.BytesIO(image_bytes))
            decoded_objects = decode(image)
            
            for obj in decoded_objects:
                data = obj.data.decode('utf-8')
                # Check se parece uma URL de SEFAZ
                if "sefaz" in data.lower() or "receita" in data.lower() or data.startswith("http"):
                    return data
            return None
        except Exception as e:
            print(f"[NFCe Error] Falha ao decodificar QR Code: {e}")
            return None

    def extract_access_key(self, url: str) -> str | None:
        """Extrai a chave de acesso de 44 dígitos da URL da SEFAZ, se houver."""
        match = re.search(r'(?:\?p=|chNFe=)([0-9]{44})', url)
        if match:
            return match.group(1)
        
        # Algumas URLs tem a chave direto no path ou outro param, fallback genérico:
        match_generic = re.search(r'[0-9]{44}', url)
        if match_generic:
            return match_generic.group(0)
            
        return None

nfce_service = NFCeService()
