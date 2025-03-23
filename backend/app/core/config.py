import secrets
import os
from typing import Any, Dict, List, Optional, Union
from pydantic import AnyHttpUrl, PostgresDsn, validator, SecretStr, EmailStr, Field
from pydantic_settings import BaseSettings
import logging

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

class EnvironmentSettings(BaseSettings):
    """Configuración básica de entorno"""
    # Entorno de ejecución
    ENVIRONMENT: str = "development"
    
    @validator("ENVIRONMENT")
    def validate_environment(cls, v):
        allowed = ["development", "testing", "staging", "production"]
        if v.lower() not in allowed:
            raise ValueError(f"Entorno debe ser uno de: {', '.join(allowed)}")
        return v.lower()
    
    class Config:
        env_file = ".env"
        case_sensitive = True

# Cargar el entorno primero
env = EnvironmentSettings().ENVIRONMENT

# Mapeo de archivos de entorno
env_files = {
    "development": [".env.development", ".env"],
    "testing": [".env.testing", ".env"],
    "staging": [".env.staging", ".env"],
    "production": [".env.production", ".env"],
}

class Settings(BaseSettings):
    # API
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "Marketplace en Tiempo Real"
    DEBUG: bool = False
    
    # Entorno
    ENVIRONMENT: str = env
    
    # JWT
    SECRET_KEY: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 días
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30  # 30 días para refresh token
    
    @validator("SECRET_KEY", pre=True)
    def validate_secret_key(cls, v, values):
        if not v or len(v) < 32:
            if env == "production":
                raise ValueError("SECRET_KEY debe tener al menos 32 caracteres en producción")
            # En desarrollo, generar una clave automáticamente
            logger.warning("SECRET_KEY no configurada o insegura, generando automáticamente")
            return secrets.token_urlsafe(32)
        return v
    
    # CORS
    BACKEND_CORS_ORIGINS: List[AnyHttpUrl] = []
    
    @validator("BACKEND_CORS_ORIGINS", pre=True)
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> Union[List[str], str]:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, (list, str)):
            return v
        raise ValueError(v)
    
    # Base de datos
    POSTGRES_SERVER: str = "db"
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = Field(..., min_length=8)
    POSTGRES_DB: str = "marketplace"
    DATABASE_URL: Optional[PostgresDsn] = None
    
    # Validación de contraseña de base de datos
    @validator("POSTGRES_PASSWORD", pre=True)
    def validate_db_password(cls, v, values):
        if env == "production" and (not v or len(v) < 12):
            raise ValueError("POSTGRES_PASSWORD debe tener al menos 12 caracteres en producción")
        return v
    
    @validator("DATABASE_URL", pre=True)
    def assemble_db_connection(cls, v: Optional[str], values: Dict[str, Any]) -> Any:
        if isinstance(v, str):
            return v
        
        # Construir DSN
        try:
            return PostgresDsn.build(
                scheme="postgresql",
                user=values.get("POSTGRES_USER"),
                password=values.get("POSTGRES_PASSWORD"),
                host=values.get("POSTGRES_SERVER"),
                path=f"/{values.get('POSTGRES_DB') or ''}",
            )
        except Exception as e:
            if env == "production":
                raise ValueError(f"Error en configuración de base de datos: {str(e)}")
            # En desarrollo, usar SQLite como fallback
            logger.warning(f"Error en configuración PostgreSQL, usando SQLite: {str(e)}")
            return "sqlite:///./marketplace.db"
    
    # Redis
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: Optional[str] = None
    REDIS_URL: Optional[str] = None
    
    @validator("REDIS_URL", pre=True)
    def assemble_redis_connection(cls, v: Optional[str], values: Dict[str, Any]) -> Any:
        if isinstance(v, str):
            return v
        
        # Construir URL de Redis
        password_part = f":{values.get('REDIS_PASSWORD')}@" if values.get('REDIS_PASSWORD') else ""
        return f"redis://{password_part}{values.get('REDIS_HOST')}:{values.get('REDIS_PORT')}/{values.get('REDIS_DB')}"
    
    # Configuración de seguridad
    SECURITY_BCRYPT_ROUNDS: int = 12  # Mayor número = más seguro pero más lento
    SECURITY_PASSWORD_SALT: Optional[str] = None
    
    @validator("SECURITY_PASSWORD_SALT", pre=True)
    def validate_password_salt(cls, v, values):
        if not v:
            # Generar salt automáticamente si no se proporciona
            return secrets.token_hex(16)
        return v
    
    # Rate limiting
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_DEFAULT_LIMIT: int = 100  # Número de solicitudes
    RATE_LIMIT_DEFAULT_PERIOD: int = 3600  # Período en segundos (1 hora)
    RATE_LIMIT_BY_IP: bool = True
    
    # Configuraciones específicas por entorno
    def get_settings_by_environment(self) -> Dict[str, Any]:
        # Configuraciones base
        settings_map = {
            "development": {
                "DEBUG": True,
                "SECURITY_BCRYPT_ROUNDS": 4,  # Más rápido para desarrollo
                "RATE_LIMIT_ENABLED": False,
            },
            "testing": {
                "DEBUG": True,
                "SECURITY_BCRYPT_ROUNDS": 4,
                "RATE_LIMIT_ENABLED": False,
            },
            "staging": {
                "DEBUG": False,
                "SECURITY_BCRYPT_ROUNDS": 10,
                "RATE_LIMIT_DEFAULT_LIMIT": 200,
            },
            "production": {
                "DEBUG": False,
                "SECURITY_BCRYPT_ROUNDS": 12,
                "RATE_LIMIT_DEFAULT_LIMIT": 100,
                "RATE_LIMIT_BY_IP": True,
            },
        }
        
        return settings_map.get(self.ENVIRONMENT, {})
    
    # Aplicar configuraciones específicas del entorno
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Actualizar con configuraciones específicas del entorno
        env_settings = self.get_settings_by_environment()
        for key, value in env_settings.items():
            if hasattr(self, key):
                setattr(self, key, value)
    
    class Config:
        case_sensitive = True
        env_file = env_files.get(env, [".env"])

# Crear instancia de configuración
settings = Settings()

# Registrar información de inicio
logger.info(f"Iniciando aplicación en entorno: {settings.ENVIRONMENT}")
logger.info(f"Depuración: {'activada' if settings.DEBUG else 'desactivada'}")
if settings.DATABASE_URL:
    db_url_safe = str(settings.DATABASE_URL)
    if settings.POSTGRES_PASSWORD:
        db_url_safe = db_url_safe.replace(str(settings.POSTGRES_PASSWORD), '****')
    logger.info(f"Base de datos: {db_url_safe}")
else:
    logger.info("Base de datos: No configurada")