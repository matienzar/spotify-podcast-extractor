import spotipy
from spotipy.oauth2 import SpotifyOAuth
import pandas as pd
from datetime import datetime
import os
from dotenv import load_dotenv
import time
import sqlite3
from typing import List, Dict, Optional
import logging
import argparse

# Import condicional para Gemini
try:
    import google.generativeai as genai
    from google.api_core.exceptions import ResourceExhausted
    GEMINI_AVAILABLE = True
except ImportError:
    genai = None  # Definir para evitar warnings
    ResourceExhausted = Exception
    GEMINI_AVAILABLE = False
    print("⚠️ google-generativeai no instalado. Categorización automática deshabilitada.")

# Configurar logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Cargar variables de entorno
load_dotenv()


class SpotifyPodcastExtractor:
    def __init__(self, client_id: Optional[str] = None, client_secret: Optional[str] = None,
                 redirect_uri: Optional[str] = None, access_token: Optional[str] = None,
                 gemini_api_key: Optional[str] = None, db_path: str = "spotify_podcasts.db",
                 model_name: str = 'gemini-1.5-flash', rpm_limit: int = 15):
        """
        Inicializa el extractor de podcasts de Spotify

        Args:
            client_id: ID de cliente de la app de Spotify
            client_secret: Secret de cliente de la app de Spotify
            redirect_uri: URI de redirección HTTPS
            access_token: Token de acceso directo (opcional, más simple)
            gemini_api_key: API key de Google Gemini para categorización
            db_path: Ruta de la base de datos SQLite
        """
        self.scope = "playlist-read-private playlist-read-collaborative"
        self.db_path = db_path
        self.model = None
        self.quota_exhausted = False
        self.rpm_limit = rpm_limit
        self.request_timestamps = []  # Para controlar el RPM

        # Configurar Spotify
        if access_token:
            self.sp = spotipy.Spotify(auth=access_token)
        else:
            if not all([client_id, client_secret, redirect_uri]):
                raise ValueError("Necesitas proporcionar access_token O (client_id + client_secret + redirect_uri)")

            self.sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
                client_id=client_id,
                client_secret=client_secret,
                redirect_uri=redirect_uri,
                scope=self.scope
            ))

        # Configurar Gemini
        self.use_gemini = False
        if gemini_api_key and GEMINI_AVAILABLE:
            try:
                genai.configure(api_key=gemini_api_key)
                self.model = genai.GenerativeModel(model_name)
                self.use_gemini = True
                logger.info(f"✅ Modelo Gemini '{model_name}' configurado correctamente")
            except Exception as e:
                logger.warning(f"⚠️ Error configurando Gemini API: {e}")
                logger.info("Continuando sin categorización automática...")
        elif gemini_api_key and not GEMINI_AVAILABLE:
            logger.warning("⚠️ Gemini API key configurada pero google-generativeai no está instalado")
            logger.info("Instala con: pip install google-generativeai")
        else:
            logger.info("ℹ️ No se configuró Gemini API - sin categorización automática")

        # Inicializar base de datos
        self._init_database()

    def _init_database(self):
        """Inicializa la base de datos SQLite"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # Crear tabla de podcasts si no existe
                cursor.execute('''
                               CREATE TABLE IF NOT EXISTS podcasts
                               (
                                   id
                                   TEXT
                                   PRIMARY
                                   KEY,
                                   titulo
                                   TEXT
                                   NOT
                                   NULL,
                                   descripcion
                                   TEXT,
                                   duracion_minutos
                                   REAL,
                                   fecha_agregado_playlist
                                   TEXT,
                                   url_spotify
                                   TEXT,
                                   categoria
                                   TEXT
                                   DEFAULT
                                   'Sin categorizar',
                                   podcast_show_name
                                   TEXT,
                                   playlist_id
                                   TEXT,
                                   fecha_procesado
                                   TEXT
                                   DEFAULT
                                   CURRENT_TIMESTAMP,
                                   UNIQUE
                               (
                                   id,
                                   playlist_id
                               ))
                               ''')

                # Crear tabla de playlists para tracking
                cursor.execute('''
                               CREATE TABLE IF NOT EXISTS playlists
                               (
                                   id
                                   TEXT
                                   PRIMARY
                                   KEY,
                                   nombre
                                   TEXT,
                                   ultima_sincronizacion
                                   TEXT
                                   DEFAULT
                                   CURRENT_TIMESTAMP
                               )
                               ''')

                conn.commit()
                logger.info(f"Base de datos inicializada: {self.db_path}")

        except sqlite3.Error as e:
            logger.error(f"Error inicializando base de datos: {e}")
            raise

    # Dentro de la clase SpotifyPodcastExtractor

    def get_existing_categories(self) -> list[str]:
        """
        Obtiene una lista única de categorías existentes de la base de datos.
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                # Selecciona categorías distintas, excluyendo las que no son útiles como guía
                cursor.execute("""
                               SELECT DISTINCT categoria
                               FROM podcasts
                               WHERE categoria IS NOT NULL
                                 AND categoria NOT IN ('Sin categorizar', 'Error categorización', '')
                               """)
                # Convierte la lista de tuplas a una lista simple de strings
                categories = [row[0] for row in cursor.fetchall()]
                return categories
        except sqlite3.Error as e:
            logger.error(f"Error obteniendo categorías existentes: {e}")
            return []

    def _throttle_requests(self):
        """Controla la velocidad de las peticiones para no exceder el límite RPM."""
        if not self.use_gemini:
            return

        now = time.time()

        # Elimina timestamps de hace más de 60 segundos
        self.request_timestamps = [t for t in self.request_timestamps if now - t < 60]

        if len(self.request_timestamps) >= self.rpm_limit:
            # Si hemos alcanzado el límite, calculamos cuánto esperar
            oldest_request_time = self.request_timestamps[0]
            wait_time = 60 - (now - oldest_request_time) + 0.1  # +0.1s de margen

            if wait_time > 0:
                logger.info(
                    f"Throttling: Límite de {self.rpm_limit} RPM alcanzado. Esperando {wait_time:.2f} segundos...")
                time.sleep(wait_time)

        # Registra el timestamp de la petición actual
        self.request_timestamps.append(time.time())

    def categorize_episode(self, title: str, description: str, show_name: str, existing_categories: list[str]) -> str:
        """
        Categoriza un episodio usando Gemini API con categorías dinámicas

        Args:
            title: Título del episodio
            description: Descripción del episodio
            show_name: Nombre del podcast/show
            existing_categories: Listado de las categorías actuales en base de datos
        Returns:
            Categoría del episodio
        """
        # Si la cuota ya se agotó en esta ejecución, no intentes llamar a la API.
        if self.quota_exhausted:
            return "Sin categorizar"

        if not self.use_gemini or not self.model:
            return "Sin categorizar"

        # Convertimos la lista de categorías a un string para el prompt
        category_list_str = ", ".join(existing_categories)

        # Creamos una sección en el prompt solo si tenemos categorías para sugerir
        guidance_prompt = ""
        if category_list_str:
            guidance_prompt = f"""
        INSTRUCCIONES ADICIONALES:
        1. Revisa la siguiente lista de categorías que ya existen: "{category_list_str}".
        2. Si una de esas categorías describe PERFECTAMENTE el episodio, úsala para mantener la consistencia.
        3. Si NINGUNA categoría existente encaja bien, siéntete libre de crear una NUEVA categoría que sea más específica y descriptiva. La precisión es más importante que la consistencia.
        """

        prompt = f"""
        Analiza este episodio de podcast y asígnale la categoría más específica y apropiada posible.

        PODCAST: {show_name}
        TÍTULO: {title}
        DESCRIPCIÓN: {description}
        {guidance_prompt}
        Instrucciones:
        1. Analiza el contenido y determina la categoría MÁS ESPECÍFICA posible
        2. Puedes crear categorías nuevas si ninguna de las comunes aplica perfectamente
        3. Usa categorías en español, específicas y descriptivas
        4. Ejemplos de buenas categorías: "Tecnología e IA", "Emprendimiento Digital", "Salud Mental", "Historia Moderna", "Ciencia y Investigación", "Marketing Digital", etc.
        5. Evita categorías demasiado amplias como "Otro" o "General"

        Responde SOLO con el nombre de la categoría, máximo 3-4 palabras, sin explicaciones adicionales.
        """

        try:
            self._throttle_requests()
            response = self.model.generate_content(prompt)
            category = response.text.strip()

            if len(category) > 50:
                category = category[:50]
            if not category or category.lower() in ['error', 'unknown', '']:
                category = "Sin categorizar"

            return category

        except ResourceExhausted:
            # ¡Error de cuota detectado!
            logger.warning(
                "⚠️ Se ha alcanzado la cuota de la API de Gemini. Se detendrá la categorización por esta sesión.")
            self.quota_exhausted = True  # Activamos el interruptor
            return "Sin categorizar"  # Marcamos como 'Sin categorizar' para reintentar mañana

        except Exception as e:
            # Otros errores de la API
            logger.warning(f"Error categorizando '{title}': {e}")
            return "Error categorización"

    def get_last_sync_date(self, playlist_id: str) -> Optional[str]:
        """Obtiene la fecha de la última sincronización de una playlist"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT ultima_sincronizacion FROM playlists WHERE id = ?", (playlist_id,))
                result = cursor.fetchone()
                return result[0] if result else None
        except sqlite3.Error as e:
            logger.error(f"Error obteniendo fecha de sincronización: {e}")
            return None

    def update_sync_date(self, playlist_id: str, playlist_name: str):
        """Actualiza la fecha de sincronización de una playlist"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO playlists (id, nombre, ultima_sincronizacion)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                ''', (playlist_id, playlist_name))
                conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Error actualizando fecha de sincronización: {e}")

    def episode_exists_in_db(self, episode_id: str, playlist_id: str) -> bool:
        """Verifica si un episodio ya existe en la base de datos"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT 1 FROM podcasts WHERE id = ? AND playlist_id = ?", (episode_id, playlist_id))
                return cursor.fetchone() is not None
        except sqlite3.Error as e:
            logger.error(f"Error verificando existencia de episodio: {e}")
            return False

    def save_episode_to_db(self, episode_data: Dict, playlist_id: str):
        """Guarda un episodio en la base de datos"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO podcasts 
                    (id, titulo, descripcion, duracion_minutos, fecha_agregado_playlist, 
                     url_spotify, categoria, podcast_show_name, playlist_id, fecha_procesado)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ''', (
                    episode_data['id'],
                    episode_data['titulo'],
                    episode_data['descripcion'],
                    episode_data['duracion_minutos'],
                    episode_data['fecha_agregado_playlist'],
                    episode_data['url_spotify'],
                    episode_data['categoria'],
                    episode_data['podcast_show_name'],
                    playlist_id
                ))
                conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Error guardando episodio en DB: {e}")

    def get_uncategorized_episodes(self) -> List[Dict]:
        """Obtiene episodios sin categorizar de la base de datos"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                               SELECT id, titulo, descripcion, podcast_show_name, playlist_id
                               FROM podcasts
                               WHERE categoria IN ('Sin categorizar', 'Error categorización', '')
                               ORDER BY fecha_procesado DESC
                               ''')

                columns = [description[0] for description in cursor.description]
                return [dict(zip(columns, row)) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            logger.error(f"Error obteniendo episodios sin categorizar: {e}")
            return []

    def update_episode_category(self, episode_id: str, playlist_id: str, categoria: str):
        """Actualiza la categoría de un episodio"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                               UPDATE podcasts
                               SET categoria = ?
                               WHERE id = ?
                                 AND playlist_id = ?
                               ''', (categoria, episode_id, playlist_id))
                conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Error actualizando categoría: {e}")

    def get_playlist_episodes(self, playlist_id: str) -> List[Dict]:
        """
        Extrae episodios de podcast de una playlist, procesando solo los nuevos

        Args:
            playlist_id: ID de la playlist de Spotify

        Returns:
            Lista de diccionarios con información de los episodios procesados
        """
        new_episodes = []

        try:
            playlist_info = self.sp.playlist(playlist_id)
            playlist_name = playlist_info['name']
            logger.info(f"Procesando playlist: {playlist_name}")

            results = self.sp.playlist_items(playlist_id, additional_types=('track',))
            episodes_processed = 0
            episodes_skipped = 0

            # Obtenemos las categorías existentes UNA SOLA VEZ al principio
            existing_categories = self.get_existing_categories()
            logger.info(f"Usando {len(existing_categories)} categorías existentes como guía.")


            while results:
                for item in results['items']:
                    if not (item['track'] and item['track']['type'] == 'episode'):
                        continue

                    episode = item['track']
                    episode_id = episode['id']

                    if self.episode_exists_in_db(episode_id, playlist_id):
                        episodes_skipped += 1
                        continue

                    try:
                        full_episode = self.sp.episode(episode_id)
                        show_info = full_episode.get('show', {})

                        descripcion = (full_episode.get('description', '') or
                                       full_episode.get('html_description', '') or
                                       'Sin descripción disponible')

                        episode_data = {
                            'id': episode_id,
                            'titulo': episode.get('name', 'Sin título'),
                            'descripcion': descripcion,
                            'duracion_minutos': round(episode.get('duration_ms', 0) / 60000, 2),
                            'fecha_agregado_playlist': item.get('added_at', 'Sin fecha'),
                            'url_spotify': episode.get('external_urls', {}).get('spotify', 'Sin URL'),
                            'podcast_show_name': show_info.get('name', 'Desconocido'),
                            'categoria': 'Sin categorizar'
                        }

                        if self.use_gemini:
                            logger.info(f"Categorizando: {episode_data['titulo']}")
                            categoria = self.categorize_episode(
                                episode_data['titulo'], descripcion, episode_data['podcast_show_name'],existing_categories )
                            episode_data['categoria'] = categoria
                            time.sleep(0.5)

                        self.save_episode_to_db(episode_data, playlist_id)
                        new_episodes.append(episode_data)
                        episodes_processed += 1
                        logger.info(f"✅ Procesado: {episode_data['titulo']} - Categoría: {episode_data['categoria']}")

                    except Exception as e:
                        logger.error(f"Error procesando episodio {episode_id}: {e}")
                        continue

                results = self.sp.next(results) if results['next'] else None

            self.update_sync_date(playlist_id, playlist_name)
            logger.info(f"Procesamiento completado: {episodes_processed} nuevos, {episodes_skipped} existentes")

        except Exception as e:
            logger.error(f"Error al procesar la playlist: {e}")
            return []

        return new_episodes

    def categorize_pending_episodes(self):
        """Categoriza episodios que no tienen categoría asignada"""

        if self.quota_exhausted:
            logger.info("⏭️ Saltando categorización de pendientes por cuota de API agotada.")
            return

        if not self.use_gemini:
            logger.warning("Gemini API no configurada, no se pueden categorizar episodios")
            return

        uncategorized = self.get_uncategorized_episodes()
        if not uncategorized:
            logger.info("No hay episodios pendientes por categorizar.")
            return

        logger.info(f"Categorizando {len(uncategorized)} episodios pendientes...")

        # Obtenemos las categorías existentes UNA SOLA VEZ antes del bucle
        existing_categories = self.get_existing_categories()
        logger.info(f"Usando {len(existing_categories)} categorías existentes como guía.")

        for episode in uncategorized:
            try:
                categoria = self.categorize_episode(
                    episode['titulo'], episode['descripcion'], episode['podcast_show_name'],existing_categories )
                self.update_episode_category(episode['id'], episode['playlist_id'], categoria)
                logger.info(f"✅ Categorizado: {episode['titulo']} -> {categoria}")
                time.sleep(0.5)

            except Exception as e:
                logger.error(f"Error categorizando {episode['titulo']}: {e}")

    def export_to_excel(self, filename: Optional[str] = None, playlist_id: Optional[str] = None) -> Optional[str]:
        """
        Exporta los datos de la base de datos a Excel

        Args:
            filename: Nombre del archivo (opcional)
            playlist_id: ID específico de playlist (opcional, si None exporta todo)

        Returns:
            Nombre del archivo generado
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                query = 'SELECT * FROM podcasts'
                params = []
                if playlist_id:
                    query += ' WHERE playlist_id = ?'
                    params.append(playlist_id)
                query += ' ORDER BY fecha_agregado_playlist DESC'
                df = pd.read_sql_query(query, conn, params=params)

            if df.empty:
                logger.warning("No hay datos para exportar")
                return None

            if not filename:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                playlist_suffix = f"_{playlist_id}" if playlist_id else "_all"
                filename = f"spotify_podcasts{playlist_suffix}_{timestamp}.xlsx"

            date_columns = ['fecha_agregado_playlist', 'fecha_procesado']
            for col in date_columns:
                if col in df.columns:
                    df[col] = pd.to_datetime(df[col], errors='coerce')

                    df[col] = df[col].dt.tz_localize(None)

            column_names = {
                'titulo': 'Título', 'descripcion': 'Descripción', 'duracion_minutos': 'Duración (min)',
                'fecha_agregado_playlist': 'Fecha Agregado', 'url_spotify': 'URL Spotify',
                'categoria': 'Categoría', 'podcast_show_name': 'Podcast', 'playlist_id': 'ID Playlist',
                'fecha_procesado': 'Fecha Procesado'
            }
            df.rename(columns=column_names, inplace=True)

            with pd.ExcelWriter(filename, engine='openpyxl') as writer:
                df.to_excel(writer, sheet_name='Podcasts', index=False)
                worksheet = writer.sheets['Podcasts']
                for column in worksheet.columns:
                    max_length = max(len(str(cell.value)) for cell in column if cell.value)
                    adjusted_width = min(max_length + 2, 50)
                    worksheet.column_dimensions[column[0].column_letter].width = adjusted_width

            logger.info(f"Archivo Excel generado: {filename}")
            logger.info(f"Total de episodios exportados: {len(df)}")
            return filename

        except Exception as e:
            logger.error(f"Error exportando a Excel: {e}")
            return None

    def reset_database(self) -> bool:
        """Resetea completamente la base de datos eliminando el archivo."""
        try:
            if os.path.exists(self.db_path):
                os.remove(self.db_path)
                logger.info(f"🗑️ Base de datos eliminada: {self.db_path}")
            self._init_database()
            logger.info("✅ Base de datos reseteada correctamente")
            return True

        except Exception as e:
            logger.error(f"Error reseteando base de datos: {e}")
            return False

    def get_database_stats(self) -> Dict:
        """Obtiene estadísticas de la base de datos"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM podcasts")
                total_episodes = cursor.fetchone()[0]
                cursor.execute("SELECT COUNT(DISTINCT categoria) FROM podcasts WHERE categoria != 'Sin categorizar'")
                total_categories = cursor.fetchone()[0]
                cursor.execute("SELECT COUNT(*) FROM podcasts WHERE categoria = 'Sin categorizar'")
                uncategorized = cursor.fetchone()[0]
                cursor.execute("SELECT COUNT(DISTINCT playlist_id) FROM podcasts")
                total_playlists = cursor.fetchone()[0]
                cursor.execute('''
                               SELECT categoria, COUNT(*) as count
                               FROM podcasts
                               WHERE categoria != 'Sin categorizar'
                               GROUP BY categoria
                               ORDER BY count DESC LIMIT 10
                               ''')
                top_categories = cursor.fetchall()

                return {
                    'total_episodes': total_episodes, 'total_categories': total_categories,
                    'uncategorized': uncategorized, 'total_playlists': total_playlists,
                    'top_categories': top_categories
                }
        except sqlite3.Error as e:
            logger.error(f"Error obteniendo estadísticas: {e}")
            return {}

    def reset_categories(self) -> bool:
        """
        Resetea la categoría de todos los episodios a 'Sin categorizar'.
        No borra ningún otro dato del episodio.

        Returns:
            True si el reseteo fue exitoso, False en caso contrario.
        """
        logger.info("🔄 Reseteando todas las categorías a 'Sin categorizar'...")
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                # Actualiza la columna 'categoria' para todas las filas
                cursor.execute("UPDATE podcasts SET categoria = 'Sin categorizar'")
                updated_rows = cursor.rowcount
                conn.commit()
                logger.info(f"✅ Se han reseteado las categorías de {updated_rows} episodios.")
                return True
        except sqlite3.Error as e:
            logger.error(f"❌ Error reseteando categorías: {e}")
            return False

def create_arg_parser():
    """Crea el parser de argumentos de línea de comandos"""
    return argparse.ArgumentParser(
        description='Extractor de podcasts de Spotify con categorización automática',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos de uso:
  python spotify_podcast_extractor.py
  python spotify_podcast_extractor.py --no-llm
  python spotify_podcast_extractor.py --reset-db
  python spotify_podcast_extractor.py --export-only
  python spotify_podcast_extractor.py --reset-categories

        """
    )

def run_app():
    """Función principal para ejecutar el extractor"""
    parser = create_arg_parser()
    parser.add_argument('--no-llm', action='store_true', help='Ejecutar sin categorización automática')
    parser.add_argument('--reset-db', action='store_true', help='Resetear la base de datos antes de ejecutar')
    parser.add_argument('--export-only', action='store_true', help='Solo exportar datos existentes a Excel')
    parser.add_argument('--playlist-id', type=str, help='ID específico de playlist (sobrescribe .env)')
    parser.add_argument('--output', type=str, help='Nombre del archivo Excel de salida')
    parser.add_argument('--reset-categories',action='store_true',help='Resetea todas las categorías a "Sin categorizar" sin borrar los episodios'
    )
    args = parser.parse_args()

    # CONFIGURACIÓN
    client_id = os.getenv('SPOTIFY_CLIENT_ID')
    client_secret = os.getenv('SPOTIFY_CLIENT_SECRET')
    redirect_uri = os.getenv('SPOTIFY_REDIRECT_URI', 'https://example.com/callback')
    playlist_id = args.playlist_id or os.getenv('SPOTIFY_PLAYLIST_ID')
    access_token = os.getenv('SPOTIFY_ACCESS_TOKEN')
    gemini_api_key = os.getenv('GEMINI_API_KEY') if not args.no_llm else None
    db_path = os.getenv('DB_PATH', 'spotify_podcasts.db')

    # --- CARGAR CONFIGURACIÓN DEL MODELO ---
    gemini_model = os.getenv('GEMINI_MODEL_NAME', 'gemini-1.5-flash')
    gemini_rpm_limit = int(os.getenv('GEMINI_RPM_LIMIT', 15))  # Default a 15 por si no está en .env

    logger.info(f"   - Modelo LLM: {gemini_model} (Límite: {gemini_rpm_limit} RPM)")

    logger.info("🔧 Configuración:")
    logger.info(
        f"   - Categorización LLM: {'❌ Deshabilitada' if args.no_llm else ('✅ Habilitada' if gemini_api_key else '⚠️ Sin API key')}")
    logger.info(f"   - Base de datos: {db_path}")
    if args.reset_db: logger.info("   - Resetear BD: ✅ Sí")
    if args.export_only: logger.info("   - Solo exportar: ✅ Sí")

    # CÓDIGO CORREGIDO
    if args.export_only:
        if not os.path.exists(db_path):
            logger.error(f"❌ No existe la base de datos: {db_path}. No se puede exportar.")
            return
        try:
            # Crea una instancia 'vacía' sin llamar a __init__ para evitar la validación de APIs
            extractor = SpotifyPodcastExtractor.__new__(SpotifyPodcastExtractor)

            # Configura manualmente solo los atributos necesarios para exportar
            extractor.db_path = db_path

            logger.info("📁 Exportando datos existentes a Excel...")
            _export_and_log_stats(extractor, args.output, args.playlist_id, export_only=True)
        except Exception as e:
            logger.error(f"Error en export-only: {e}")
        return

    if not playlist_id:
        logger.error("❌ Error: SPOTIFY_PLAYLIST_ID no configurado. Usa --playlist-id o configúralo en .env")
        return

    try:
        if access_token:
            logger.info("🔑 Usando token de acceso directo...")
            extractor = SpotifyPodcastExtractor(access_token=access_token, gemini_api_key=gemini_api_key,
                                                db_path=db_path,model_name=gemini_model,rpm_limit=gemini_rpm_limit)
        elif client_id and client_secret:
            logger.info("🔑 Usando OAuth con client_id/secret...")
            extractor = SpotifyPodcastExtractor(client_id, client_secret, redirect_uri, gemini_api_key=gemini_api_key,
                                                db_path=db_path,model_name=gemini_model,rpm_limit=gemini_rpm_limit)
        else:
            logger.error(
                "❌ CONFIGURACIÓN REQUERIDA: Revisa tu .env. Faltan SPOTIFY_ACCESS_TOKEN o (SPOTIFY_CLIENT_ID + SPOTIFY_CLIENT_SECRET).")
            return
    except Exception as e:
        logger.error(f"❌ Error inicializando el extractor: {e}")
        return

    try:
        if args.reset_db:
            if not extractor.reset_database():
                logger.error("❌ Error reseteando base de datos")
                return
        elif args.reset_categories:  # Usamos 'elif' para que no se ejecute si ya se reseteó la BD entera
            logger.info("🔄 Reseteando solo las categorías...")
            if not extractor.reset_categories():
                return  # Si falla el reseteo de categorías, no continuar

        stats = extractor.get_database_stats()
        if stats and stats.get('total_episodes', 0) > 0:
            logger.info(
                f"📊 Estadísticas de la BD: {stats['total_episodes']} episodios, {stats['total_categories']} categorías, {stats['uncategorized']} sin categorizar")

        logger.info("🔍 Buscando nuevos episodios en la playlist...")
        new_episodes = extractor.get_playlist_episodes(playlist_id)

        if new_episodes:
            logger.info(f"✅ Se procesaron {len(new_episodes)} nuevos episodios")
        else:
            logger.info("ℹ️ No se encontraron episodios nuevos")

        if not args.no_llm:
            extractor.categorize_pending_episodes()
        else:
            logger.info("⏭️ Saltando categorización (--no-llm activado)")

        logger.info("📁 Exportando a Excel...")
        _export_and_log_stats(extractor, args.output, playlist_id)

    except Exception as e:
        logger.error(f"❌ Error durante la ejecución: {e}")

def _export_and_log_stats(extractor: SpotifyPodcastExtractor, output_file: Optional[str],
                          playlist_id: Optional[str], export_only: bool = False):
    """Función auxiliar para exportar a Excel y mostrar estadísticas."""
    filename = extractor.export_to_excel(output_file, playlist_id)

    if filename:
        status = "¡Export completado!" if export_only else "¡Proceso completado!"
        logger.info(f"🎉 ¡{status}! Archivo generado: {filename}")
        stats = extractor.get_database_stats()
        if stats and stats.get('top_categories'):
            logger.info("🏆 Top 5 categorías:")
            for cat, count in stats['top_categories'][:5]:
                logger.info(f"   - {cat}: {count} episodios")
    else:
        logger.warning("⚠️ No se pudo generar el archivo Excel (puede que no haya datos).")


if __name__ == "__main__":
    import sys

    if len(sys.argv) == 1 or '--help' in sys.argv or '-h' in sys.argv:
        logger.info("=" * 60)
        logger.info("📦 Dependencias necesarias:")
        logger.info("   pip install spotipy pandas openpyxl python-dotenv")
        logger.info("   pip install google-generativeai  # Opcional para LLM")
        logger.info("=" * 60)

    run_app()