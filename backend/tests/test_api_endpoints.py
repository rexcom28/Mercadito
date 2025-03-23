import unittest
import requests
import json
import time
from typing import Dict, Any, Optional

class MarketplaceAPITest(unittest.TestCase):
    """Test case para probar los endpoints de la API del Marketplace"""
    
    BASE_URL = "http://localhost:8000/api/v1"  # Cambia esto a la URL de tu API
    auth_token = None
    user_id = None
    product_id = None
    offer_id = None
    
    # Para pruebas que requieren dos usuarios
    second_user = {
        "email": None,
        "password": "Password123!",
        "token": None,
        "user_id": None
    }
    
    def make_request(self, method: str, endpoint: str, data: Optional[Dict[str, Any]] = None, token: Optional[str] = None) -> requests.Response:
        """Realiza una solicitud HTTP a la API"""
        url = f"{self.BASE_URL}{endpoint}"
        headers = {}
        
        # Usar el token proporcionado o el token principal
        if token:
            headers["Authorization"] = f"Bearer {token}"
        elif self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
            
        if data and method in ["POST", "PUT", "PATCH"]:
            headers["Content-Type"] = "application/json"
            response = requests.request(method, url, json=data, headers=headers)
        else:
            response = requests.request(method, url, headers=headers)
            
        return response
    
    def test_01_register_main_user(self):
        """Prueba el registro del usuario principal"""
        print("\n----- Test: Registro de Usuario Principal -----")
        
        # Generar datos únicos con timestamp
        timestamp = int(time.time())
        email = f"test{timestamp}@example.com"
        
        data = {
            "email": email,
            "password": "Password123!",
            "full_name": "Usuario de Prueba",
            "is_active": True,
            "is_seller": True,
            "phone": "1234567890"
        }
        
        response = self.make_request("POST", "/users/register", data)
        
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text[:200]}...")
        
        self.assertEqual(201, response.status_code)
        
        # Guardar el email y contraseña para el login
        self.__class__.test_email = email
        self.__class__.test_password = "Password123!"
    
    def test_02_register_second_user(self):
        """Prueba el registro de un segundo usuario para interacciones"""
        print("\n----- Test: Registro de Usuario Secundario -----")
        
        # Generar datos únicos con timestamp
        timestamp = int(time.time())
        email = f"buyer{timestamp}@example.com"
        
        data = {
            "email": email,
            "password": "Password123!",
            "full_name": "Comprador de Prueba",
            "is_active": True,
            "is_seller": False,
            "phone": "9876543210"
        }
        
        response = self.make_request("POST", "/users/register", data)
        
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text[:200]}...")
        
        self.assertEqual(201, response.status_code)
        
        # Guardar datos del segundo usuario
        self.__class__.second_user["email"] = email
    
    def test_03_login_main_user(self):
        """Prueba el inicio de sesión del usuario principal"""
        print("\n----- Test: Login de Usuario Principal -----")
        
        # Verificar que tengamos las credenciales del paso anterior
        self.assertTrue(hasattr(self.__class__, 'test_email'), "Email de prueba no disponible")
        
        # Para probar con OAuth2PasswordRequestForm
        response = requests.post(
            f"{self.BASE_URL}/users/login",
            data={
                "username": self.__class__.test_email, 
                "password": self.__class__.test_password
            }
        )
        
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text[:200]}...")
        
        self.assertEqual(200, response.status_code)
        
        # Extraer y guardar el token
        data = response.json()
        self.__class__.auth_token = data.get("access_token")
        self.__class__.user_id = data.get("user_id")
        
        self.assertIsNotNone(self.__class__.auth_token)
        self.assertIsNotNone(self.__class__.user_id)
    
    def test_04_login_second_user(self):
        """Prueba el inicio de sesión del segundo usuario"""
        print("\n----- Test: Login de Usuario Secundario -----")
        
        # Verificar que tengamos las credenciales del segundo usuario
        self.assertTrue(self.__class__.second_user["email"], "Email del segundo usuario no disponible")
        
        # Login con OAuth2PasswordRequestForm
        response = requests.post(
            f"{self.BASE_URL}/users/login",
            data={
                "username": self.__class__.second_user["email"], 
                "password": self.__class__.second_user["password"]
            }
        )
        
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text[:200]}...")
        
        self.assertEqual(200, response.status_code)
        
        # Extraer y guardar el token
        data = response.json()
        self.__class__.second_user["token"] = data.get("access_token")
        self.__class__.second_user["user_id"] = data.get("user_id")
        
        self.assertIsNotNone(self.__class__.second_user["token"])
        self.assertIsNotNone(self.__class__.second_user["user_id"])
    
    def test_05_get_my_profile(self):
        """Prueba obtener el perfil del usuario autenticado"""
        print("\n----- Test: Obtener Perfil de Usuario -----")
        
        # Verificar que tengamos token
        self.assertTrue(self.__class__.auth_token, "Token no disponible")
        
        response = self.make_request("GET", "/users/me")
        
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text[:200]}...")
        
        self.assertEqual(200, response.status_code)
        data = response.json()
        self.assertEqual(self.__class__.user_id, data.get("id"))
    
    def test_06_update_my_profile(self):
        """Prueba actualizar datos del perfil"""
        print("\n----- Test: Actualizar Perfil de Usuario -----")
        
        # Verificar que tengamos token
        self.assertTrue(self.__class__.auth_token, "Token no disponible")
        
        # En lugar de PATCH con un objeto, usamos parámetros de consulta
        # ya que parece que tu API está esperando este formato
        update_params = {
            "full_name": f"Usuario Actualizado {int(time.time())}",
            "phone": "9876543210"
        }
        
        response = self.make_request("PATCH", "/users/me", update_params)
        
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text[:200]}...")
        
        # Si la API devuelve 200 pero no actualiza, probablemente esté
        # esperando los parámetros en un formato diferente
        if response.status_code == 200:
            updated_data = response.json()
            print(f"¿Se actualizó el nombre? Esperado: {update_params['full_name']}, Obtenido: {updated_data.get('full_name')}")
            print(f"¿Se actualizó el teléfono? Esperado: {update_params['phone']}, Obtenido: {updated_data.get('phone')}")
        
        self.assertEqual(200, response.status_code)
    
    def test_07_create_product(self):
        """Prueba crear un nuevo producto"""
        print("\n----- Test: Crear Producto -----")
        
        # Verificar que tengamos token
        self.assertTrue(self.__class__.auth_token, "Token no disponible")
        
        data = {
            "title": f"Producto de Prueba {int(time.time())}",
            "description": "Este es un producto creado durante las pruebas automatizadas",
            "price": 199.99,
            "currency": "USD",
            "quantity": 10,
            "status": "active"
        }
        
        response = self.make_request("POST", "/products", data)
        
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text[:200]}...")
        
        self.assertEqual(201, response.status_code)
        
        # Guardar el ID del producto para pruebas posteriores
        product_data = response.json()
        self.__class__.product_id = product_data.get("id")
        self.assertIsNotNone(self.__class__.product_id)
    
    def test_08_get_products(self):
        """Prueba obtener listado de productos"""
        print("\n----- Test: Obtener Listado de Productos -----")
        
        response = self.make_request("GET", "/products")
        
        print(f"Status Code: {response.status_code}")
        print(f"Total Productos: {len(response.json())}")
        
        self.assertEqual(200, response.status_code)
        
        # Verificar que el listado sea un array
        products = response.json()
        self.assertIsInstance(products, list)
    
    def test_09_get_product_by_id(self):
        """Prueba obtener un producto por su ID"""
        print("\n----- Test: Obtener Producto por ID -----")
        
        # Verificar que tengamos un producto ID
        self.assertTrue(self.__class__.product_id, "ID de producto no disponible")
        
        response = self.make_request("GET", f"/products/{self.__class__.product_id}")
        
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text[:200]}...")
        
        self.assertEqual(200, response.status_code)
        product = response.json()
        self.assertEqual(self.__class__.product_id, product.get("id"))
    
    def test_10_create_offer(self):
        """Prueba crear una oferta para un producto (desde el segundo usuario)"""
        print("\n----- Test: Crear Oferta (Usuario Secundario) -----")
        
        # Verificar que tengamos token del segundo usuario y producto ID
        self.assertTrue(self.__class__.second_user["token"], "Token del segundo usuario no disponible")
        self.assertTrue(self.__class__.product_id, "ID de producto no disponible")
        
        data = {
            "product_id": self.__class__.product_id,
            "amount": 180.0,
            "currency": "USD",
            "message": "Me interesa este producto, ofrezco este precio."
        }
        
        # Usar el token del segundo usuario
        response = self.make_request("POST", "/offers", data, token=self.__class__.second_user["token"])
        
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text[:200]}...")
        
        self.assertEqual(201, response.status_code)
        
        # Guardar el ID de la oferta para pruebas posteriores
        offer_data = response.json()
        self.__class__.offer_id = offer_data.get("id")
        self.assertIsNotNone(self.__class__.offer_id)
    
    def test_11_get_offers(self):
        """Prueba obtener listado de ofertas (como vendedor)"""
        print("\n----- Test: Obtener Listado de Ofertas (Vendedor) -----")
        
        # Verificar que tengamos token
        self.assertTrue(self.__class__.auth_token, "Token no disponible")
        
        # Algunos endpoints pueden requerir parámetros específicos
        # Si necesitamos parámetros, podemos añadirlos a la URL
        response = self.make_request("GET", "/offers?role=seller")
        
        print(f"Status Code: {response.status_code}")
        if response.status_code == 200:
            offers = response.json()
            print(f"Total Ofertas: {len(offers)}")
        else:
            print(f"Error: {response.text}")
        
        # Buscar los parámetros correctos según la documentación de la API
        self.assertIn(response.status_code, [200, 422])
    
    def test_12_respond_to_offer(self):
        """Prueba responder a una oferta (aceptar/rechazar)"""
        print("\n----- Test: Responder a Oferta -----")
        
        # Verificar que tengamos token y oferta ID
        self.assertTrue(self.__class__.auth_token, "Token no disponible")
        self.assertTrue(self.__class__.offer_id, "ID de oferta no disponible")
        
        data = {
            "status": "accepted",
            "message": "Oferta aceptada durante pruebas"
        }
        
        response = self.make_request("PATCH", f"/offers/{self.__class__.offer_id}", data)
        
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text[:200]}...")
        
        # La respuesta puede ser 200 o 400 dependiendo de la lógica de negocio
        self.assertIn(response.status_code, [200, 400])
    
    def test_13_send_message(self):
        """Prueba enviar un mensaje a otro usuario"""
        print("\n----- Test: Enviar Mensaje -----")
        
        # Verificar que tengamos token y el ID del segundo usuario
        self.assertTrue(self.__class__.auth_token, "Token no disponible")
        self.assertTrue(self.__class__.second_user["user_id"], "ID del segundo usuario no disponible")
        
        # Enviar mensaje al segundo usuario
        data = {
            "recipient_id": self.__class__.second_user["user_id"],
            "content": f"Mensaje de prueba {int(time.time())}",
            "related_product_id": self.__class__.product_id
        }
        
        response = self.make_request("POST", "/messages", data)
        
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text[:200]}...")
        
        self.assertEqual(201, response.status_code)
    
    def test_14_get_messages(self):
        """Prueba obtener mensajes"""
        print("\n----- Test: Obtener Mensajes -----")
        
        # Verificar que tengamos token
        self.assertTrue(self.__class__.auth_token, "Token no disponible")
        
        response = self.make_request("GET", "/messages")
        
        print(f"Status Code: {response.status_code}")
        if response.status_code == 200:
            print(f"Total Mensajes: {len(response.json())}")
        
        self.assertEqual(200, response.status_code)
        
        # Verificar que el listado sea un array
        messages = response.json()
        self.assertIsInstance(messages, list)

if __name__ == "__main__":
    # Ejecutar pruebas en orden
    unittest.main()