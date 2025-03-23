# scripts/download_swagger_ui.py
import os
import urllib.request
import shutil

def download_swagger_ui_files():
    """Descarga archivos de Swagger UI para uso local"""
    # Asegurarse que el directorio existe
    static_dir = "static"
    os.makedirs(static_dir, exist_ok=True)
    
    # Archivos a descargar
    files = {
        "swagger-ui-bundle.js": "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.12.0/swagger-ui-bundle.js",
        "swagger-ui.css": "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.12.0/swagger-ui.css",
        "favicon-32x32.png": "https://fastapi.tiangolo.com/img/favicon.png"
    }
    
    for filename, url in files.items():
        filepath = os.path.join(static_dir, filename)
        print(f"Descargando {url} a {filepath}...")
        try:
            urllib.request.urlretrieve(url, filepath)
            print(f"✅ Archivo descargado correctamente: {filename}")
        except Exception as e:
            print(f"❌ Error al descargar {filename}: {e}")

if __name__ == "__main__":
    download_swagger_ui_files()