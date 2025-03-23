# Marketplace en Tiempo Real - MVP

Un marketplace interactivo en tiempo real donde vendedores y compradores pueden interactuar dinámicamente, con notificaciones instantáneas y sistema de ofertas.

## Características principales

- Registro de usuarios con perfiles de comprador y vendedor
- Listado de productos con imágenes
- Comunicación en tiempo real mediante WebSockets
- Sistema de ofertas y contraofertas
- Notificaciones instantáneas

## Requisitos técnicos

- Docker y Docker Compose
- VPS con KVM2 (mínimo 2 vCPU, 8GB RAM)
- Dominio y certificados SSL (para producción)

## Estructura del proyecto

El proyecto sigue una arquitectura de microservicios containerizados:

- **API REST** con FastAPI
- **WebSockets** para comunicación en tiempo real
- **PostgreSQL** para datos persistentes
- **Redis** para gestión de conexiones y pub/sub
- **Nginx** como proxy inverso y servidor web

## Configuración inicial

### 1. Clonar el repositorio

```bash
git clone https://github.com/tu-usuario/marketplace-mvp.git
cd marketplace-mvp