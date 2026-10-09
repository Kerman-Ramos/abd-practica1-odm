__author__ = 'Pablo Ramos Criado'
__students__ = 'Kerman Ramos y Rodrigo Castro'


from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut
import time
from typing import Generator, Any, Self
from geojson import Point
import pymongo
from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
from bson.objectid import ObjectId
import yaml

def getLocationPoint(address: str) -> Point:
	""" 
	Obtiene las coordenadas de una dirección en formato geojson.Point
	Utilizar la API de geopy para obtener las coordenadas de la direccion
	Cuidado, la API es publica tiene limite de peticiones, utilizar sleeps.

	Parameters
	----------
		address : str
			direccion completa de la que obtener las coordenadas
	Returns
	-------
		geojson.Point
			coordenadas del punto de la direccion
	"""
	
	# Traduce una dirección de texto a un punto matemático (Longitud, Latitud) usando una API.
	# Incluye un sistema de reintentos con pausas (sleep) para evitar bloqueos de red.
	# Lanza un error fatal si la conversión fracasa, garantizando que el sistema 
	# nunca guarde coordenadas nulas o inventadas.
	
	location = None
	intentos = 0
	maxIntentos = 5
	while location is None and intentos < maxIntentos:
		intentos += 1
		try:
			time.sleep(1)
			location = Nominatim(user_agent="envivo-abd-p1-rodrigo-kerman").geocode(address)
		except GeocoderTimedOut:
			# Puede lanzar una excepcion si se supera el tiempo de espera
			# Volver a intentarlo
			continue
	
	# TODO terminado
	
	if location is None:
		raise ValueError(f"No se pudieron obtener coordenadas para: {address}")
	return Point((location.longitude, location.latitude))

class Model:
	""" 
	Clase de modelo abstracta
	Crear tantas clases que hereden de esta clase como  
	colecciones/modelos se deseen tener en la base de datos.

	Attributes
	----------
		required_vars : set[str]
			conjunto de atributos requeridos por el modelo
		admissible_vars : set[str]
			conjunto de atributos admitidos por el modelo
		db : pymongo.collection.Collection
			conexion a la coleccion de la base de datos
	
	Methods
	-------
		__setattr__(name: str, value: str | dict) -> None
			Sobreescribe el metodo de asignacion de valores a los 
			atributos del objeto con el fin de controlar qué atributos 
			son modificados y cuando son modificados.
		__getattr__(name: str) -> Any
			Sobreescribe el metodo de acceso a atributos del objeto 
		save()  -> None
			Guarda el modelo en la base de datos
		delete() -> None
			Elimina el modelo de la base de datos
		find(filter: dict[str, str | dict]) -> ModelCursor
			Realiza una consulta de lectura en la BBDD.
			Devuelve un cursor de modelos ModelCursor
		aggregate(pipeline: list[dict]) -> pymongo.command_cursor.CommandCursor
			Devuelve el resultado de una consulta aggregate.
		find_by_id(id: str) -> dict | None
			Busca un documento por su id utilizando la cache y lo devuelve.
			Si no se encuentra el documento, devuelve None.
		init_class(db_collection: pymongo.collection.Collection, required_vars: set[str], admissible_vars: set[str]) -> None
			Inicializa las variables de clase en la inicializacion del sistema.

	"""
	_required_vars: set[str]
	_admissible_vars: set[str]
	_location_var: str | None = None
	_db: pymongo.collection.Collection
	_internal_vars: set[str] = frozenset(('_modified_vars', '_required_vars', '_admissible_vars', '_db', '_data', '_location_var'))

	def __init__(self, **kwargs: dict[str, str | dict | list]) -> None:
		"""
		Inicializa el modelo con los valores proporcionados en kwargs
		Comprueba que los valores proporcionados en kwargs son admitidos
		por el modelo y que las atributos requeridos son proporcionadas.

		Parameters
		----------
			kwargs : dict[str, str | dict]
				diccionario con los valores de las atributos del modelo
		"""

		# Actúa como la aduana de la memoria RAM al instanciar el objeto.
		# Cruza los datos entrantes contra el esquema del YAML usando teoría de conjuntos.
		# Bloquea la creación si falta un campo requerido o si intentan inyectar uno no admitido.
		# Si todo es legal, encapsula la información en el diccionario interno _data.

		self._data: dict[str, str | dict | list] = {}

		# TODO terminado
		
		self._modified_vars = set()

		permitidas = self._required_vars | self._admissible_vars | {'_id'}
		if self._location_var:
			permitidas.add(self._location_var + '_loc')
		
		kwargsSet = set(kwargs)
		
		faltan = self._required_vars - kwargsSet
		if faltan:
			raise ValueError(f"Faltan atributos requeridos: {sorted(faltan)}")

		sobran = kwargsSet - permitidas
		if sobran:
			raise ValueError(f"Atributos no admitidos: {sorted(sobran)}")

		self._data.update(kwargs)

	def __setattr__(self, name: str, value: str | dict) -> None:
		""" Sobreescribe el metodo de asignacion de valores a los 
		atributos del objeto con el fin de controlar que atributos 
		son modificados y cuando son modificados.
		"""

		# Cortafuegos en tiempo de ejecución para controlar la mutación del objeto.
		# Intercepta cualquier asignación (=) para verificar si la variable pertenece al esquema.
		# Si es válida, la guarda en _data y registra su nombre en _modified_vars,
		# creando un historial exacto para que el método 'save' solo envíe las diferencias por la red.

		if name in self._internal_vars:
			super().__setattr__(name, value)
			return
		
		# TODO terminado
		
		permitidas = self._required_vars | self._admissible_vars | {'_id'}
		if self._location_var:
			permitidas.add(self._location_var + '_loc')

		if name not in permitidas:
			raise ValueError(f"Atributo no admitido: {name}")

		# Asigna el valor value a la variable name
		self._data[name] = value
		self._modified_vars.add(name)

	def __getattr__(self, name: str) -> Any:
		""" Sobreescribe el metodo de acceso a atributos del objeto
		__getattr__ solo es llamado cuando no encuentra el atributo
		en el objeto 
		"""

		# Redirige las peticiones de lectura del objeto hacia el diccionario interno _data.
		# Si el motor de Python busca una variable estructural del sistema, 
		# devuelve el control al comportamiento nativo para no romper la arquitectura.

		if name in self._internal_vars:
			return super().__getattribute__(name)
		try:
			return self._data[name]
		except KeyError:
			raise AttributeError
		
	def save(self) -> None:
		"""
		Guarda el modelo en la base de datos
		Si el modelo no existe en la base de datos, se crea un nuevo
		documento con los valores del modelo. En caso contrario, se
		actualiza el documento existente con los nuevos valores del
		modelo.
		"""
		"""if self._id is None:
			result = pymongo.collection.insert_one(self)

			self._id = result.inserted_id
			return self._id
		else:"""

		# Sincroniza el estado de la RAM con la base de datos física.
		# Si es un documento nuevo, calcula sus coordenadas (si aplica), lo inserta completo 
		# y recupera su _id. Si ya existe, lee el historial de mutaciones (_modified_vars)
		# y envía exclusivamente un parche ($set) a la red, optimizando el ancho de banda.

		# TODO terminado

		loc_var = self._location_var

		if "_id" not in self._data:
			# Si no existe
			doc = dict(self._data)
			
			if loc_var and loc_var in doc:
				doc[loc_var + "_loc"] = getLocationPoint(doc[loc_var])

			# Inserta en Mongo (pymongo añade el "_id" a doc)
			self._db.insert_one(doc)
			# Sincroniza la memoria con lo guardado ("_id" y punto)
			self._data.update(doc)
		else:
			# Si existe
			cambios = {campo: self._data[campo] for campo in self._modified_vars}
			
			if loc_var and loc_var in cambios:
				punto = getLocationPoint(cambios[loc_var])
				cambios[loc_var + "_loc"] = punto
				self._data[loc_var + "_loc"] = punto
			
			if cambios:
				self._db.update_one({"_id": self._data["_id"]}, {"$set": cambios})

		self._modified_vars = set()

	def delete(self) -> None:
		"""
		Elimina el modelo de la base de datos
		"""

		# Destruye el documento físicamente en MongoDB utilizando su identificador único (_id).
		# Tras el borrado, elimina el _id de la memoria RAM para que el objeto 
		# vuelva a considerarse un "documento nuevo" si se intentara guardar de nuevo.

		# TODO terminado

		if "_id" in self._data:
			self._db.delete_one({"_id": self._data["_id"]})
			del self._data["_id"]
	
	@classmethod
	def find(cls, filter: dict[str, str | dict]) -> Any:
		""" 
		Utiliza el metodo find de pymongo para realizar una consulta
		de lectura en la BBDD.
		find debe devolver un cursor de modelos ModelCursor

		Parameters
		----------
			filter : dict[str, str | dict]
				diccionario con el criterio de busqueda de la consulta
		Returns
		-------
			ModelCursor
				cursor de modelos
		""" 

		# Ejecuta una consulta de lectura delegando el filtro al motor de MongoDB.
		# Envuelve el resultado nativo dentro del iterador 'ModelCursor' 
		# para transformarlo posteriormente en objetos puros de nuestra clase.
		
		# TODO terminado
		
		cursor = cls._db.find(filter)
		return ModelCursor(cls, cursor)

	@classmethod
	def aggregate(cls, pipeline: list[dict]) -> pymongo.command_cursor.CommandCursor:
		""" 
		Devuelve el resultado de una consulta aggregate. 
		No hay nada que hacer en esta funcion.
		Se utilizara para las consultas solicitadas
		en el segundo proyecto de la practica.

		Parameters
		----------
			pipeline : list[dict]
				lista de etapas de la consulta aggregate 
		Returns
		-------
			pymongo.command_cursor.CommandCursor
				cursor de pymongo con el resultado de la consulta
		""" 

		# Canaliza las consultas analíticas complejas directamente hacia 
		# el motor de agregación de MongoDB, devolviendo el resultado computado.

		return cls._db.aggregate(pipeline)
	
	@classmethod
	def find_by_id(cls, id: str) -> Self | None:
		""" 
		NO IMPLEMENTAR HASTA EL TERCER PROYECTO
		Busca un documento por su id utilizando la cache y lo devuelve.
		Si no se encuentra el documento, devuelve None.

		Parameters
		----------
			id : str
				id del documento a buscar
		Returns
		-------
			Self | None
				Modelo del documento encontrado o None si no se encuentra
		""" 
		#TODO
		pass

	@classmethod
	def init_class(cls, db_collection: pymongo.collection.Collection, indexes:dict[str,str], required_vars: set[str], admissible_vars: set[str]) -> None:
		""" 
		Inicializa los atributos de clase en la inicializacion del sistema.
		Aqui se deben inicializar o asegurar los indices. Tambien se puede
		alguna otra inicialización/comprobaciones o cambios adicionales
		que estime el alumno.

		Parameters
		----------
			db_collection : pymongo.collection.Collection
				Conexion a la collecion de la base de datos.
			indexes: Dict[str,str]
				Set de indices y tipo de indices para la coleccion
			required_vars : set[str]
				Set de atributos requeridos por el modelo
			admissible_vars : set[str] 
				Set de atributos admitidos por el modelo
		"""

		# Configura el enlace físico entre la clase en Python y la colección en MongoDB.
		# Transforma las reglas del YAML en órdenes directas para que el motor 
		# construya los árboles de búsqueda (índices), aplicando el sufijo '_loc' a la geometría.

		cls._db = db_collection
		cls._required_vars = required_vars
		cls._admissible_vars = admissible_vars
		
		# TODO terminado
		
		for campo, tipo in (indexes or {}).items():
			if tipo == 'unique':
				cls._db.create_index([(campo, pymongo.ASCENDING)], unique=True)
			elif tipo == 'asc':
				cls._db.create_index([(campo, pymongo.ASCENDING)])
			elif tipo == 'geosphere':
				cls._location_var = campo
				cls._db.create_index([(campo + "_loc", pymongo.GEOSPHERE)])
		

class ModelCursor:
	""" 
	Cursor para iterar sobre los documentos del resultado de una
	consulta. Los documentos deben ser devueltos en forma de objetos
	modelo.

	Attributes
	----------
		model_class : Model
			Clase para crear los modelos de los documentos que se iteran.
		cursor : pymongo.cursor.Cursor
			Cursor de pymongo a iterar

	Methods
	-------
		__iter__() -> Generator
			Devuelve un iterador que recorre los elementos del cursor
			y devuelve los documentos en forma de objetos modelo.
	"""

	def __init__(self, model_class: Model, cursor: pymongo.cursor.Cursor):
		"""
		Inicializa el cursor con la clase de modelo y el cursor de pymongo

		Parameters
		----------
			model_class : Model
				Clase para crear los modelos de los documentos que se iteran.
			cursor: pymongo.cursor.Cursor
				Cursor de pymongo a iterar
		"""

		# Vincula el cursor crudo devuelto por MongoDB con la clase del modelo 
		# correspondiente, preparando el entorno para la instanciación de los datos.

		self.model = model_class
		self.cursor = cursor
	
	def __iter__(self) -> Generator:
		"""
		Devuelve un iterador que recorre los elementos del cursor
		y devuelve los documentos en forma de objetos modelo.
		Utilizar yield para generar el iterador
		Utilizar la funcion next para obtener el siguiente documento del cursor
		Utilizar alive para comprobar si existen mas documentos.
		"""

		# Consume los resultados de MongoDB bajo demanda para no colapsar la memoria RAM.
		# Extrae un diccionario de la red, lo convierte en un objeto validado de nuestra clase,
		# y pausa la ejecución (yield) hasta que el programa solicite el siguiente registro.

		# TODO terminado

		while self.cursor.alive:
			try:
				doc = next(self.cursor)
			except StopIteration:
				break
			yield self.model(**doc)


def initApp(definitions_path: str = "./models.yml", mongodb_uri="mongodb://localhost:27017/", db_name="abd", scope=globals()) -> None:
	""" 
	Declara las clases que heredan de Model para cada uno de los 
	modelos de las colecciones definidas en definitions_path.
	Inicializa las clases de los modelos proporcionando los indices y 
	atributos admitidos y requeridos para cada una de ellas y la conexión a la
	collecion de la base de datos.
	
	Parameters
	----------
		definitions_path : str
			ruta al fichero de definiciones de modelos
		mongodb_uri : str
			uri de conexion a la base de datos
		db_name : str
			nombre de la base de datos
	"""

	# Motor de arranque (Metaprogramación).
	# Levanta la conexión a MongoDB, lee el mapa estructural del YAML y forja dinámicamente 
	# las clases de negocio (Recinto, Evento, etc.) en tiempo de ejecución.
	# Finalmente, inyecta las reglas en cada clase y dispara la creación de índices en el servidor.
	
	# TODO terminado

	# Inicializar base de datos
	client = MongoClient(mongodb_uri, server_api=ServerApi('1'))
	db = client[db_name]

	# Leer el fichero de definiciones de modelos
	with open(definitions_path, encoding="utf-8") as f:
		definiciones = yaml.safe_load(f)

	# Declarar una clase modelo por cada coleccion definida en el YAML
	for nombre, definicion in definiciones.items():
		indexes = {}
		for campo in definicion.get("unique_indexes") or []:
			indexes[campo] = "unique"
		for campo in definicion.get("regular_indexes") or []:
			indexes[campo] = "asc"
		location = definicion.get("location_index")
		if location:
			indexes[location] = "geosphere"

		scope[nombre] = type(nombre, (Model,), {})
		scope[nombre].init_class(
			db_collection=db[nombre],
			indexes=indexes,
			required_vars=set(definicion.get("required_vars") or []),
			admissible_vars=set(definicion.get("admissible_vars") or []),
		)

		# Ejemplo de declaracion de modelo para colecion llamada MiModelo
#	scope["MiModelo"] = type("MiModelo", (Model,),{})
		# La clase se declara en tiempo de ejecucion y queda en scope, que no tiene
		# por que ser el espacio de nombres global: las pruebas le pasan su propio
		# diccionario. Por eso se inicializa a traves de scope y no por su nombre,
		# que ahi todavia no existe.
#	scope["MiModelo"].init_class(db_collection=None, indexes=None, required_vars=None, admissible_vars=None)

if __name__ == '__main__':
	
	# Inicializar base de datos y modelos con initApp
	# TODO terminado
	
	initApp()

	# Limpiar documentos de ejecuciones anteriores (los indices se mantienen)
	Recinto._db.delete_many({})

	# Crear modelo
	r = Recinto(nombre="WiZink Center", direccion="Av. Felipe II, Madrid", aforo=17000)

	# Asignar nuevo valor a variable admitida del objeto 
	r.zonas = {"pista": 8000, "grada": 9000}

	# Asignar nuevo valor a variable no admitida del objeto 
	try:
		r.color = "rojo"
	except ValueError as e:
		print("Rechazado correctamente:", e)

	# Guardar
	r.save()

	# Asignar nuevo valor a variable admitida del objeto
	r.aforo = 17500

	# Guardar
	r.save()

	# Buscar nuevo documento con find
	cursor = Recinto.find({"nombre": "WiZink Center"})

	# Obtener primer documento
	primero = next(iter(cursor))
	print(primero.nombre, primero.aforo)

	# Modificar valor de variable admitida
	primero.aforo = 18000
	
	# Guardar
	primero.save()

	print(Recinto._db.find_one({"nombre": "WiZink Center"}))


	# Para crear los JSON poner True
	if True:
		# MOTOR DE EXTRACCIÓN (VOLCADO JSON)
		from bson import json_util
		print("\n--- INICIANDO EXTRACCIÓN Y VOLCADO JSON ---")
		
		# Crear una base de datos con informacion de ejemplo para exportar a JSON
		Recinto._db.delete_many({})
		Artista._db.delete_many({})
		Evento._db.delete_many({})
		Asistente._db.delete_many({})

		print("--- INICIANDO POBLACIÓN DE LA BASE DE DATOS ---")

		# 3. CREACIÓN DE NODOS INDEPENDIENTES
		# Recinto (Lanzará una petición a la API para traducir la dirección)
		r = Recinto(
			nombre="WiZink Center", 
			direccion="Av. Felipe II, Madrid", 
			aforo=17000,
			zonas={"pista": 8000, "grada": 9000}
		)
		r.save()
		print("Recinto guardado con éxito.")

		# Artistas (Sin coordenadas, para probar que el if de la función save es seguro)
		a1 = Artista(
			nombre="Avicii", 
			generos=["Electrónica", "Dance"], 
			pais_origen="Suecia", 
			anio_inicio=2006
		)
		a1.save()

		a2 = Artista(
			nombre="C. Tangana", 
			generos=["Urbano", "Pop", "Flamenco"], 
			pais_origen="España", 
			anio_inicio=2006
		)
		a2.save()
		print("Artistas guardados con éxito.")

		# Asistente (Lanzará petición a la API. Usamos una dirección real y verificable)
		usr = Asistente(
			nombre="Estudiante Analítico",
			email="estudiante.utad@example.com",
			fecha_alta="2026-09-22",
			direccion="Calle de Alcalá 1, Madrid", 
			generos_preferidos=["Electrónica", "Urbano"]
		)
		usr.save()
		print("Asistente guardado con éxito.")

		# 4. CREACIÓN DEL NODO RELACIONAL
		# El Evento une el ecosistema. Su integridad depende de que los nombres coincidan 
		# lógicamente con los registros anteriores.
		e1 = Evento(
			titulo="Tributo Electrónico: Wake Me Up",
			artistas=["Avicii"],
			recinto="WiZink Center",
			fecha="2026-11-20T21:00:00Z",
			precios_zona={"pista": 60, "grada": 45},
			entradas_vendidas=15000
		)
		e1.save()

		e2 = Evento(
			titulo="El Madrileño Live",
			artistas=["C. Tangana"],
			recinto="WiZink Center",
			fecha="2026-12-05T20:30:00Z",
			precios_zona={"pista": 80, "grada": 65},
			entradas_vendidas=17000
		)
		e2.save()
		print("Eventos guardados con éxito.")

		# 5. MOTOR DE EXTRACCIÓN (VOLCADO JSON)
		print("\n--- INICIANDO EXTRACCIÓN Y VOLCADO JSON ---")
		
		# Agrupamos los moldes de las entidades que queremos exportar al disco.
		colecciones = [Recinto, Artista, Evento, Asistente]

		for modelo in colecciones:
			nombre_archivo = f"{modelo.__name__}.json"
			
			# Conectamos directamente a la capa física (_db) para extraer la estructura cruda
			documentos_crudos = list(modelo._db.find({}))
			
			# Abrimos el túnel de escritura y forzamos el formato utf-8 (vital en español)
			with open(nombre_archivo, "w", encoding="utf-8") as archivo_salida:
				
				# El serializador json_util interviene para traducir objetos matemáticos
				# (como el ObjectId de MongoDB o las coordenadas) a texto plano JSON.
				texto_json = json_util.dumps(documentos_crudos, ensure_ascii=False, indent=4)
				archivo_salida.write(texto_json)
				
			print(f"Volcado físico generado: {nombre_archivo} ({len(documentos_crudos)} registros)")

		print("\nPROCESO ARQUITECTÓNICO FINALIZADO CORRECTAMENTE.")