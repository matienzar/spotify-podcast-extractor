import spotipy
from spotipy.oauth2 import SpotifyOAuth
import pandas as pd
from datetime import datetime
import os
from dotenv import load_dotenv
import time
import sqlite3
import json
from typing import List, Dict, Optional
import logging
import argparse

# Import condicional para Gemini
try:
    import google.generativeai as genai
    from google.api_core.exceptions import ResourceExhausted

    GEMINI_AVAILABLE = True
except ImportError:
    genai = None
    ResourceExhausted = Exception
    GEMINI_AVAILABLE = False
    print(
        "⚠️ google-generativeai no instalado. Categorización automática deshabilitada."
    )

# Configurar logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Cargar variables de entorno
load_dotenv()


class SpotifyPodcastExtractor:
    def __init__(
        self,
        client_id: Optional[str],
        client_secret: Optional[str],
        redirect_uri: Optional[str],
        gemini_api_key: Optional[str] = None,
        db_path: str = "spotify_podcasts.db",
        model_name: str = "gemini-1.5-flash",
        rpm_limit: int = 15,
        max_categories: int = 10,
    ):
        self.scope = "playlist-read-private playlist-read-collaborative"
        self.db_path = db_path
        self.model = None
        self.quota_exhausted = False
        self.rpm_limit = rpm_limit
        self.request_timestamps = []
        self.max_categories = max_categories
        self.sp = None  # Inicializamos la conexión a None

        # --- CONEXIÓN A SPOTIFY SOLO SI SE PROVEEN CREDENCIALES ---
        if all([client_id, client_secret, redirect_uri]):
            self.sp = spotipy.Spotify(
                auth_manager=SpotifyOAuth(
                    client_id=client_id,
                    client_secret=client_secret,
                    redirect_uri=redirect_uri,
                    scope=self.scope,
                    cache_path=".spotipyoauthcache",
                )
            )

        # Configuración de Gemini
        self.use_gemini = False
        if gemini_api_key and GEMINI_AVAILABLE:
            try:
                genai.configure(api_key=gemini_api_key)
                self.model = genai.GenerativeModel(model_name)
                self.use_gemini = True
                logger.info(f"✅ Modelo Gemini '{model_name}' configurado.")
            except Exception as e:
                logger.warning(f"⚠️ Error configurando Gemini API: {e}.")

        self._init_database()

    def _init_database(self):
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                               CREATE TABLE IF NOT EXISTS podcasts
                               (
                                   id
                                   TEXT
                                   NOT
                                   NULL,
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
                                   TEXT
                                   NOT
                                   NULL,
                                   fecha_procesado
                                   TEXT
                                   DEFAULT
                                   CURRENT_TIMESTAMP,
                                   PRIMARY
                                   KEY
                               (
                                   id,
                                   playlist_id
                               )
                                   )
                               """
                )
                cursor.execute(
                    """
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
                               """
                )
                conn.commit()
                logger.info(f"Base de datos inicializada: {self.db_path}")
        except sqlite3.Error as e:
            logger.error(f"Error de base de datos: {e}", exc_info=True)
            raise

    def _throttle_requests(self):
        if not self.use_gemini:
            return
        now = time.time()
        self.request_timestamps = [t for t in self.request_timestamps if now - t < 60]
        if len(self.request_timestamps) >= self.rpm_limit:
            wait_time = 60 - (now - self.request_timestamps[0]) + 0.1
            if wait_time > 0:
                logger.info(
                    f"Límite de {self.rpm_limit} RPM alcanzado. Esperando {wait_time:.2f}s..."
                )
                time.sleep(wait_time)
        self.request_timestamps.append(time.time())

    def _get_existing_categories(self) -> List[str]:
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT DISTINCT categoria FROM podcasts WHERE categoria != 'Sin categorizar'"
                )
                return [row[0] for row in cursor.fetchall()]
        except sqlite3.Error as e:
            logger.error(f"No se pudieron obtener las categorías existentes: {e}")
            return []

    def _categorize_episodes_batch(
        self, episodes: List[Dict], existing_categories: List[str]
    ) -> Dict[str, str]:
        if (
            self.quota_exhausted
            or not self.use_gemini
            or not self.model
            or not episodes
        ):
            return {}

        episodes_for_prompt = [
            {
                "id": ep["id"],
                "titulo": ep["titulo"],
                "descripcion": ep["descripcion"][:400],
            }
            for ep in episodes
        ]

        if existing_categories:
            num_existing = len(existing_categories)
            can_create = self.max_categories - num_existing
            prompt_context = (
                f"Actualmente ya existen {num_existing} categorías: {', '.join(existing_categories)}. "
                f"**DEBES PRIORIZAR su uso**. Puedes crear hasta {max(0, can_create)} categorías nuevas si es necesario."
            )
        else:
            prompt_context = (
                "No hay categorías preexistentes. Debes crearlas desde cero."
            )

        prompt = f"""
        ROL: Eres un asistente de IA experto en clasificación de contenido.
        OBJETIVO: Agrupar una lista de podcasts en un sistema de categorías coherente y limitado.
        RESTRICCIÓN CRÍTICA E INQUEBRANTABLE:
        El número total de categorías ÚNICAS en toda tu respuesta NO PUEDE ser superior a {self.max_categories}. Esta es la regla más importante.
        CONTEXTO DE CATEGORÍAS:
        {prompt_context}
        PROCESO:
        1. Analiza el contenido de TODOS los episodios en el JSON de entrada.
        2. Decide qué categorías vas a usar, obedeciendo la RESTRICCIÓN CRÍTICA y el CONTEXTO.
        3. Asigna UNA SOLA categoría a cada episodio. Las categorías deben ser concisas (2-3 palabras).
        FORMATO DE SALIDA:
        Tu respuesta DEBE SER un único objeto JSON válido, sin texto, comentarios o explicaciones adicionales.
        JSON DE ENTRADA:
        {json.dumps(episodes_for_prompt, ensure_ascii=False, indent=2)}
        Genera el objeto JSON de respuesta.
        """

        logger.info("=" * 80)
        logger.info("PROMPT QUE SE ENVIARÁ A GEMINI:")
        logger.info(prompt)
        logger.info("=" * 80)

        response = None
        try:
            logger.info(f"Enviando lote de {len(episodes)} episodios a Gemini...")
            self._throttle_requests()
            response = self.model.generate_content(prompt)
            cleaned_response_text = (
                response.text.strip().replace("```json", "").replace("```", "").strip()
            )
            categorization_map = json.loads(cleaned_response_text)

            unique_categories_in_response = set(categorization_map.values())
            logger.info(
                f"LLM ha generado {len(unique_categories_in_response)} categorías únicas para este lote."
            )

            return categorization_map
        except (ResourceExhausted, json.JSONDecodeError, Exception) as e:
            if isinstance(e, ResourceExhausted):
                logger.warning("⚠️ Cuota de API de Gemini agotada.")
                self.quota_exhausted = True
            elif isinstance(e, json.JSONDecodeError):
                error_text = response.text if response else "Sin respuesta recibida."
                logger.error(f"Error de formato JSON.\nRespuesta: {error_text}")
            else:
                logger.error(f"Error en categorización: {e}", exc_info=True)
            return {}

    def get_playlist_episodes(self, playlist_id: str) -> List[Dict]:
        try:
            playlist_info = self.sp.playlist(playlist_id)
            playlist_name = playlist_info["name"]
            logger.info(f"Procesando playlist: {playlist_name}")
            results = self.sp.playlist_items(playlist_id, additional_types=("track",))
            episodes_to_process, episodes_skipped = [], 0
            while results:
                for item in results["items"]:
                    if not (
                        item
                        and item.get("track")
                        and item["track"]["type"] == "episode"
                    ):
                        continue

                    episode_summary = item["track"]
                    episode_id = episode_summary["id"]

                    if self.episode_exists_in_db(episode_id, playlist_id):
                        episodes_skipped += 1
                        continue

                    full_episode_details = self.sp.episode(episode_id)
                    descripcion = (
                        full_episode_details.get("description", "")
                        or full_episode_details.get("html_description", "")
                        or "Sin descripción"
                    )

                    episodes_to_process.append(
                        {
                            "id": episode_id,
                            "titulo": episode_summary.get("name", "Sin título"),
                            "descripcion": descripcion,
                            "duracion_minutos": round(
                                episode_summary.get("duration_ms", 0) / 60000, 2
                            ),
                            "fecha_agregado_playlist": item.get(
                                "added_at", "Sin fecha"
                            ),
                            "url_spotify": episode_summary.get("external_urls", {}).get(
                                "spotify", "Sin URL"
                            ),
                            "podcast_show_name": full_episode_details.get(
                                "show", {}
                            ).get("name", "Desconocido"),
                            "categoria": "Sin categorizar",
                        }
                    )
                results = (
                    self.sp.next(results) if results and results.get("next") else None
                )

            if self.use_gemini and episodes_to_process:
                existing_categories = self._get_existing_categories()
                logger.info(
                    f"Se usarán {len(existing_categories)} categorías existentes como contexto."
                )
                categorization_map = self._categorize_episodes_batch(
                    episodes_to_process, existing_categories
                )
                for ep in episodes_to_process:
                    ep["categoria"] = categorization_map.get(
                        ep["id"], "Sin categorizar"
                    )

            for ep in episodes_to_process:
                self.save_episode_to_db(ep, playlist_id)

            logger.info(
                f"Completado: {len(episodes_to_process)} nuevos procesados, {episodes_skipped} ya existían."
            )
            self.update_sync_date(playlist_id, playlist_name)
            return episodes_to_process
        except Exception as e:
            logger.error(f"Error al procesar la playlist: {e}", exc_info=True)
            return []

    def categorize_pending_episodes(self):
        if self.quota_exhausted or not self.use_gemini:
            return
        uncategorized = self.get_uncategorized_episodes()
        if not uncategorized:
            logger.info("No hay episodios pendientes.")
            return
        logger.info(f"Encontrados {len(uncategorized)} episodios pendientes.")
        existing_categories = self._get_existing_categories()
        logger.info(f"Se usarán {len(existing_categories)} categorías como contexto.")
        categorization_map = self._categorize_episodes_batch(
            uncategorized, existing_categories
        )
        updated_count = 0
        for ep in uncategorized:
            if ep["id"] in categorization_map:
                self.update_episode_category(
                    ep["id"], ep["playlist_id"], categorization_map[ep["id"]]
                )
                updated_count += 1
        logger.info(f"Se actualizaron {updated_count} episodios.")

    def episode_exists_in_db(self, episode_id: str, playlist_id: str) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            return (
                conn.cursor()
                .execute(
                    "SELECT 1 FROM podcasts WHERE id = ? AND playlist_id = ?",
                    (episode_id, playlist_id),
                )
                .fetchone()
                is not None
            )

    def save_episode_to_db(self, ep_data: Dict, playlist_id: str):
        with sqlite3.connect(self.db_path) as conn:
            conn.cursor().execute(
                """
                INSERT OR REPLACE INTO podcasts (id, titulo, descripcion, duracion_minutos, 
                fecha_agregado_playlist, url_spotify, categoria, podcast_show_name, playlist_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    ep_data["id"],
                    ep_data["titulo"],
                    ep_data["descripcion"],
                    ep_data["duracion_minutos"],
                    ep_data["fecha_agregado_playlist"],
                    ep_data["url_spotify"],
                    ep_data["categoria"],
                    ep_data["podcast_show_name"],
                    playlist_id,
                ),
            )
            conn.commit()

    def update_sync_date(self, playlist_id: str, playlist_name: str):
        with sqlite3.connect(self.db_path) as conn:
            conn.cursor().execute(
                "INSERT OR REPLACE INTO playlists (id, nombre, ultima_sincronizacion) VALUES (?, ?, CURRENT_TIMESTAMP)",
                (playlist_id, playlist_name),
            )
            conn.commit()

    def get_uncategorized_episodes(self) -> List[Dict]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, titulo, descripcion, podcast_show_name, playlist_id FROM podcasts WHERE categoria = 'Sin categorizar'"
            )
            return [
                dict(zip([c[0] for c in cursor.description], row))
                for row in cursor.fetchall()
            ]

    def update_episode_category(self, ep_id: str, pl_id: str, cat: str):
        with sqlite3.connect(self.db_path) as conn:
            conn.cursor().execute(
                "UPDATE podcasts SET categoria = ? WHERE id = ? AND playlist_id = ?",
                (cat, ep_id, pl_id),
            )
            conn.commit()

    def export_to_excel(
        self, filename: Optional[str] = None, playlist_id: Optional[str] = None
    ) -> Optional[str]:
        try:
            with sqlite3.connect(self.db_path) as conn:
                query = (
                    "SELECT * FROM podcasts"
                    + (" WHERE playlist_id = ?" if playlist_id else "")
                    + " ORDER BY fecha_agregado_playlist DESC"
                )
                df = pd.read_sql_query(
                    query, conn, params=[playlist_id] if playlist_id else []
                )
            if df.empty:
                logger.warning("No hay datos para exportar.")
                return None
            if not filename:
                filename = f"spotify_podcasts_{playlist_id or 'all'}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            for col in ["fecha_agregado_playlist", "fecha_procesado"]:
                if col in df.columns:
                    df[col] = pd.to_datetime(df[col], errors="coerce").dt.tz_localize(
                        None
                    )
            df.rename(
                columns={
                    "titulo": "Título",
                    "descripcion": "Descripción",
                    "duracion_minutos": "Duración (min)",
                    "fecha_agregado_playlist": "Fecha Agregado",
                    "url_spotify": "URL Spotify",
                    "categoria": "Categoría",
                    "podcast_show_name": "Podcast",
                    "playlist_id": "ID Playlist",
                    "fecha_procesado": "Fecha Procesado",
                },
                inplace=True,
            )
            with pd.ExcelWriter(filename, engine="openpyxl") as writer:
                df.to_excel(writer, sheet_name="Podcasts", index=False)
                for column_cells in writer.sheets["Podcasts"].columns:
                    length = max(len(str(cell.value)) for cell in column_cells)
                    writer.sheets["Podcasts"].column_dimensions[
                        column_cells[0].column_letter
                    ].width = min(length + 2, 60)
            logger.info(f"Archivo Excel generado: {filename}")
            return filename
        except Exception as e:
            logger.error(f"Error exportando a Excel: {e}")
            return None

    def get_database_stats(self) -> Dict:
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM podcasts")
                total = cursor.fetchone()[0]
                cursor.execute(
                    "SELECT categoria, COUNT(*) FROM podcasts GROUP BY categoria ORDER BY 2 DESC"
                )
                top_cat = cursor.fetchall()
                return {"total_episodes": total, "top_categories": top_cat}
        except Exception as e:
            logger.error(f"Error obteniendo stats: {e}")
            return {}


def main():
    parser = argparse.ArgumentParser(
        description="Extrae y categoriza podcasts de Spotify.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    # ... (La definición de los argumentos del parser no cambia)
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "-p",
        "--playlist",
        dest="playlist_id",
        help="ID de la playlist a procesar. Sobrescribe la .env.",
    )
    mode_group.add_argument(
        "--categorize-only",
        action="store_true",
        help="Solo categoriza episodios pendientes.",
    )
    mode_group.add_argument(
        "--export-only",
        action="store_true",
        help="Solo exporta la base de datos a Excel.",
    )
    parser.add_argument(
        "--no-llm", action="store_true", help="Desactiva la categorización con Gemini."
    )
    parser.add_argument(
        "--reset-db",
        action="store_true",
        help="Elimina la base de datos antes de empezar.",
    )
    parser.add_argument(
        "-o", "--output", dest="output_file", help="Nombre del archivo Excel de salida."
    )
    parser.add_argument(
        "--playlist-id-for-export",
        dest="playlist_id_for_export",
        help="(Opcional con --export-only) Exporta solo esta playlist.",
    )
    args = parser.parse_args()

    db_path = "spotify_podcasts.db"
    if args.reset_db:
        if (
            input(
                f"¿Seguro que quieres borrar la base de datos '{db_path}'? (s/N): "
            ).lower()
            == "s"
        ):
            try:
                if os.path.exists(db_path):
                    os.remove(db_path)
                    logger.info("✅ Base de datos reseteada.")
                else:
                    logger.info("No existía base de datos para resetear.")
            except Exception as e:
                logger.error(f"Error reseteando DB: {e}", exc_info=True)
        else:
            logger.info("Operación cancelada.")
        return logger.info("Todo OK")
    # Carga de configuración
    client_id = os.getenv("SPOTIFY_CLIENT_ID")
    client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")
    redirect_uri = os.getenv("SPOTIFY_REDIRECT_URI")
    gemini_api_key = os.getenv("GEMINI_API_KEY") if not args.no_llm else None
    model_name = os.getenv("GEMINI_MODEL_NAME", "gemini-1.5-flash")
    max_categories = int(os.getenv("MAX_CATEGORIES", "10"))
    playlist_id_from_env = os.getenv("SPOTIFY_PLAYLIST_ID")

    playlist_id = args.playlist_id or playlist_id_from_env

    try:
        # --- LÓGICA DE VALIDACIÓN CORREGIDA ---
        if args.export_only:
            # Para exportar, no necesitamos credenciales de Spotify
            extractor = SpotifyPodcastExtractor(
                client_id=None,
                client_secret=None,
                redirect_uri=None,
                gemini_api_key=None,
            )
            logger.info("🏃‍♂️ Modo: solo exportar.")
            _export_and_log_stats(
                extractor, args.output_file, args.playlist_id_for_export
            )
        else:
            # Para el resto de tareas, sí validamos las credenciales
            if not all([client_id, client_secret, redirect_uri]):
                return logger.error(
                    "❌ Faltan credenciales de Spotify (SPOTIPY_CLIENT_ID, etc.) en el archivo .env."
                )

            if not gemini_api_key and not args.no_llm:
                logger.warning(
                    "⚠️ GEMINI_API_KEY no configurado. Se omitirá la categorización."
                )

            extractor = SpotifyPodcastExtractor(
                client_id=client_id,
                client_secret=client_secret,
                redirect_uri=redirect_uri,
                gemini_api_key=gemini_api_key,
                model_name=model_name,
                max_categories=max_categories,
            )

            if args.categorize_only:
                logger.info("🏃‍♂️ Modo: solo categorizar pendientes.")
                extractor.categorize_pending_episodes()
                _export_and_log_stats(extractor, args.output_file, None)
            else:  # Flujo principal por defecto
                if not playlist_id:
                    return logger.error(
                        "❌ No se ha definido un ID de playlist (con -p o en SPOTIFY_PLAYLIST_ID)."
                    )
                logger.info(f"Iniciando proceso para la playlist: {playlist_id}")
                extractor.get_playlist_episodes(playlist_id=playlist_id)
                extractor.categorize_pending_episodes()
                _export_and_log_stats(extractor, args.output_file, playlist_id)

    except Exception as e:
        logger.error(f"❌ Error en la ejecución: {e}", exc_info=True)


def _export_and_log_stats(
    extractor: SpotifyPodcastExtractor,
    output_file: Optional[str],
    playlist_id: Optional[str],
):
    filename = extractor.export_to_excel(output_file, playlist_id)
    if filename:
        logger.info(f"🎉 ¡Proceso completado! Archivo generado: {filename}")
        stats = extractor.get_database_stats()
        if stats and stats.get("top_categories"):
            logger.info("🏆 Top 5 categorías:")
            for cat, count in stats["top_categories"][:5]:
                logger.info(f"   - {cat}: {count} episodios")
    else:
        logger.warning("⚠️ No se generó el archivo Excel (puede que no haya datos).")


if __name__ == "__main__":
    main()
