import pytest
import time
from pathlib import Path
from unittest.mock import patch, MagicMock
from geojson import Point
from geopy.exc import GeocoderTimedOut
from pymongo import MongoClient
from pymongo.server_api import ServerApi
from ODM import initApp, getLocationPoint, ModelCursor

# Configuration Constants

DB_NAME = "abd_test"
MONGO_URI = "mongodb://localhost:27017/"
TEST_YML_FILE_PATH = str(Path(__file__).parent / "models_test.yml")
COLLECTION_NAME = "User"

# Fixtures for Database Setup and Teardown

# Suplantar el modulo time DENTRO de ODM, y solo para no esperar.
#
# patch("ODM.time.sleep") parchea el atributo del modulo time, que es el mismo
# objeto para todo el proceso: los hilos de monitorizacion de pymongo dejan de
# dormir y se quedan girando, y la suite pasa de medio segundo a decenas de
# segundos de CPU. Sustituyendo el nombre 'time' dentro de ODM, el resto del
# proceso sigue durmiendo como debe.
class SinEsperas:
	"""Delega todo en el modulo time menos sleep, que no hace nada."""

	def __getattr__(self, nombre):
		return getattr(time, nombre)

	def sleep(self, segundos):
		return None


_cliente = None

def get_client():
	"""
	Un unico MongoClient para toda la suite: get_collection() se llama en casi
	todas las pruebas, y abrir un cliente nuevo en cada llamada deja
	conexiones y hilos de monitorizacion abiertos hasta que termina pytest.
	"""
	global _cliente
	if _cliente is None:
		_cliente = MongoClient(MONGO_URI, server_api=ServerApi('1'))
	return _cliente

@pytest.fixture(scope="session", autouse=True)
def cierra_el_cliente():
	yield
	global _cliente
	if _cliente is not None:
		_cliente.close()
		_cliente = None

@pytest.fixture(autouse=True)
def sin_llamadas_a_geopy():
	"""
	Simula Nominatim y la espera de rate-limiting en toda la suite.

	Las tres pruebas de getLocationPoint traen su propio @patch de Nominatim,
	que se aplica despues de este y es el que manda dentro de cada una. Lo que
	aporta este fixture es que ninguna implementacion golpee la API publica al
	guardar, y que los reintentos no cuesten ocho segundos de espera: no se
	esta probando que el sleep funcione.
	"""
	with patch("ODM.Nominatim") as Nominatim_mock, patch("ODM.time", SinEsperas(), create=True):
		ubicacion = MagicMock()
		ubicacion.longitude, ubicacion.latitude = -3.7038, 40.4168
		Nominatim_mock.return_value.geocode.return_value = ubicacion
		yield Nominatim_mock

@pytest.fixture(scope="function")
def db_scope():
	"""
	Pytest fixture to initialize the ODM models and MongoDB test database.
	Automatically tears down the database after each test.
	"""
	scope = {}
	get_client().drop_database(DB_NAME)
	initApp(definitions_path=TEST_YML_FILE_PATH, mongodb_uri=MONGO_URI, db_name=DB_NAME, scope=scope)
	yield scope
	get_client().drop_database(DB_NAME)

def get_collection():
	"""
	Returns the MongoDB collection used for testing.
	"""
	return get_client()[DB_NAME][COLLECTION_NAME]

# ODM Model Tests

def test_model_class_creation(db_scope):
	"""Ensure model class 'User' is created from YAML definitions."""
	assert "User" in db_scope

def test_model_attribute_registration(db_scope): 
	"""Check required and admissible attributes are correctly registered."""
	User = db_scope["User"]
	assert "name" in User._required_vars
	assert "email" in User._required_vars
	assert "age" not in User._required_vars
	assert "age" in User._admissible_vars
	assert User._location_var == "address"

def test_single_document_save(db_scope):
	"""Test saving a single document to the database."""
	User = db_scope["User"]
	user = User(name="Paco", email="paco@gmail.com", age=18)
	user.save()
	doc = get_collection().find_one({"name": "Paco", "email": "paco@gmail.com", "age": 18})
	assert doc is not None
	assert all(key in doc for key in ["name", "email", "age"])

def test_multiple_document_save(db_scope):
	"""Test saving multiple documents to the database."""
	User = db_scope["User"]
	for i in range(10):
		user = User(name=f"Paco{i}", email=f"paco{i}@gmail.com", age=18+i)
		user.save()
	docs = list(get_collection().find({}))
	assert len(docs) == 10

def test_document_deletion(db_scope):
	"""Test deleting a document from the database."""
	User = db_scope["User"]
	user = User(name="Paco", email="paco@gmail.com", age=18)
	user.save()
	user.delete()
	doc = get_collection().find_one({"name": "Paco", "email": "paco@gmail.com", "age": 18})
	assert doc is None

def test_add_attributes_before_save(db_scope):
	"""Test adding admissible attributes before saving."""
	User = db_scope["User"]
	user = User(name="Paco", email="paco@gmail.com")
	user.age = 18
	user.save()
	doc = get_collection().find_one({"name": "Paco", "email": "paco@gmail.com", "age": 18})
	assert doc is not None

def test_find_one_model_instance(db_scope):
	"""Test finding a single model instance."""
	User = db_scope["User"]
	user = User(name="Paco", email="paco@gmail.com", age=18)
	user.save()
	obj_model_cursor = User.find({})
	docs = list(obj_model_cursor)
	assert type(obj_model_cursor) is ModelCursor
	assert len(docs) == 1
	assert type(docs[0]) is User
	assert all(key in docs[0]._data for key in ["name", "email", "age"])

def test_find_specific_model_instance(db_scope):
	"""Test finding a specific model instance by attributes."""
	User = db_scope["User"]
	user = User(name="Paco", email="paco@gmail.com", age=18)
	user.save()
	docs = list(User.find({"name": "Paco", "email": "paco@gmail.com", "age": 18}))
	assert len(docs) == 1
	assert docs[0]._data["name"] == "Paco"
	assert docs[0]._data["email"] == "paco@gmail.com"
	assert docs[0]._data["age"] == 18
	assert type(docs[0]) is User

def test_find_multiple_model_instances(db_scope):
	"""Test finding multiple model instances."""
	User = db_scope["User"]
	for i in range(10):
		user = User(name=f"Paco{i}", email=f"paco{i}@gmail.com", age=18+i)
		user.save()
	docs = list(User.find({}))
	assert len(docs) == 10
	assert type(docs[0]) is User

# Geolocation Tests

@patch("ODM.Nominatim")
def test_get_location_point_success(mock_nominatim):
	mock_geolocator = MagicMock()
	mock_geolocator.geocode.return_value = MagicMock(latitude=40.7128, longitude=-74.0060)
	mock_nominatim.return_value = mock_geolocator

	result = getLocationPoint("New York, NY")
	assert isinstance(result, Point)
	assert result.coordinates == [-74.0060, 40.7128]

@patch("ODM.Nominatim")
def test_get_location_point_timeout_recovery(mock_nominatim):
	"""Test geolocation with a recoverable timeout."""
	mock_geolocator = MagicMock()
	mock_geolocator.geocode.side_effect = [GeocoderTimedOut(), MagicMock(latitude=48.8566, longitude=2.3522)]
	mock_nominatim.return_value = mock_geolocator

	result = getLocationPoint("Paris, France")
	assert isinstance(result, Point)
	assert result.coordinates == [2.3522, 48.8566]

@patch("ODM.Nominatim")
def test_get_location_point_timeout_failure(mock_nominatim):
	"""Test geolocation with repeated timeouts leading to failure."""
	mock_geolocator = MagicMock()
	mock_geolocator.geocode.side_effect = GeocoderTimedOut()
	mock_nominatim.return_value = mock_geolocator

	with pytest.raises(ValueError, match="No se pudieron obtener coordenadas"):
		getLocationPoint("Dirección que falla")