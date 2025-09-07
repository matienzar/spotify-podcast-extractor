# Spotify Podcast Extractor con IA

Extrae información detallada de podcasts de tus playlists de Spotify, los categoriza automáticamente usando Gemini AI, y exporta los datos a Excel con persistencia en base de datos SQLite.

## 🚀 Características Principales

- ✅ **Extracción completa**: Título, descripción, duración, fechas, URLs
- 🤖 **Categorización automática**: Usa Gemini AI para clasificar episodios inteligentemente
- 💬 **Preguntas y Respuestas**: Pregunta en lenguaje natural sobre el contenido de tus podcasts
- 💾 **Base de datos persistente**: SQLite para evitar procesar episodios duplicados
- 📊 **Exportación a Excel**: Formato profesional con columnas ajustadas
- 🔄 **Sincronización inteligente**: Solo procesa episodios nuevos
- 🎯 **Múltiples modos**: Extracción, categorización, o solo exportar
- ⚙️ **Control de cuota**: Gestión automática de límites de API
- 🔒 **Seguridad**: Variables de entorno para credenciales

## 📋 Requisitos

- **Python 3.7+**
- **Cuenta de Spotify Developer**
- **Gemini API Key** (opcional, para categorización automática)

## 🛠️ Instalación

### 1. Clona el repositorio
```bash
git clone https://github.com/tu-usuario/spotify-podcast-extractor.git
cd spotify-podcast-extractor
```

### 2. Instala las dependencias
```bash
pip install -r requirements.txt
```

### 3. Configura las variables de entorno
```bash
cp .env.example .env
```

Edita el archivo `.env` con tus credenciales reales:

```bash
# === SPOTIFY API ===
SPOTIFY_CLIENT_ID=tu_client_id_real
SPOTIFY_CLIENT_SECRET=tu_client_secret_real  
SPOTIFY_REDIRECT_URI=https://example.com/callback
SPOTIFY_PLAYLIST_ID=tu_playlist_id_real

# === GEMINI AI (OPCIONAL) ===
GEMINI_API_KEY=tu_gemini_api_key_real
GEMINI_MODEL_NAME=gemini-2.5-flash
GEMINI_RPM_LIMIT=10
MAX_CATEGORIES=8
```

## ⚙️ Configuración Inicial

### 🎵 Configurar Spotify Developer App

1. Ve a [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)
2. Crea una nueva aplicación
3. En **"Redirect URIs"** añade: `https://example.com/callback`
4. Copia el `Client ID` y `Client Secret`

### 🆔 Obtener ID de Playlist

1. Abre tu playlist en Spotify
2. Copia la URL: `https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M`
3. El ID es: `37i9dQZF1DXcBWIGoYBM5M`

### 🤖 Configurar Gemini AI (Opcional)

1. Ve a [Google AI Studio](https://aistudio.google.com/app/apikey)
2. Crea una API Key gratuita
3. Añádela como `GEMINI_API_KEY` en tu `.env`

> **💡 Sin Gemini**: El script funciona perfectamente sin IA, solo omite la categorización automática.

## 🚀 Uso

### Modo Básico (Recomendado)
```bash
python spotify_podcast_extractor.py
```

### Procesar Playlist Específica
```bash
python spotify_podcast_extractor.py -p PLAYLIST_ID_AQUI
```

### Modos Especializados

#### Solo Categorizar Episodios Pendientes
```bash
python spotify_podcast_extractor.py --categorize-only
```

#### Realizar una Pregunta sobre los Episodios
```bash
python spotify_podcast_extractor.py -q "¿Qué episodios hablan de startups?"
```

#### Solo Exportar Base de Datos Existente
```bash
python spotify_podcast_extractor.py --export-only
```

#### Exportar Playlist Específica
```bash
python spotify_podcast_extractor.py --export-only --playlist-id-for-export PLAYLIST_ID
```

#### Desactivar IA
```bash
python spotify_podcast_extractor.py --no-llm
```

#### Resetear Base de Datos
```bash
python spotify_podcast_extractor.py --reset-db
```

#### Archivo de Salida Personalizado
```bash
python spotify_podcast_extractor.py -o mi_archivo_podcasts.xlsx
```

### 🔐 Primera Ejecución (OAuth)

1. El script abrirá automáticamente tu navegador
2. Inicia sesión en Spotify y autoriza la aplicación
3. Spotify te redirigirá a `https://example.com/callback?code=...`
4. **La página mostrará "no encontrada" - ¡es normal!**
5. Copia la URL completa de la barra de direcciones
6. Pégala en la terminal cuando se solicite
7. Las credenciales se guardan automáticamente para futuros usos

## 📊 Datos Extraídos

Para cada episodio de podcast:

| Campo | Descripción |
|-------|-------------|
| **Título** | Nombre del episodio |
| **Descripción** | Descripción completa del episodio |
| **Podcast** | Nombre del show/podcast |
| **Duración (min)** | Duración en minutos |
| **Fecha Agregado** | Cuándo se añadió a la playlist |
| **URL Spotify** | Enlace directo al episodio |
| **Categoría** | Clasificación automática por IA |
| **ID Playlist** | Identificador de la playlist |
| **Fecha Procesado** | Cuándo se extrajo la información |

## 🤖 Categorización Inteligente

### Cómo Funciona
- **Gemini AI** analiza título y descripción de cada episodio
- Agrupa episodios en categorías coherentes y limitadas
- **Reutiliza categorías existentes** para mantener consistencia
- **Respeta el límite máximo** de categorías configurado

### Configuración de IA
```bash
# Modelo a usar (más potente = más preciso, más caro)
GEMINI_MODEL_NAME=gemini-2.5-flash  # Recomendado: rápido y preciso

# Control de cuota (peticiones por minuto)
GEMINI_RPM_LIMIT=10  # Ajusta según tu plan

# Máximo de categorías totales
MAX_CATEGORIES=8  # Evita fragmentación excesiva
```

### Ejemplos de Categorías Generadas
- "Tecnología"
- "Desarrollo Personal"
- "Negocios"
- "Historia"
- "Ciencia"

---

## 💬 Preguntas y Respuestas con IA

Una vez que has procesado tus playlists, puedes usar la IA para "conversar" con tu base de datos de episodios.

### Cómo Funciona
- **Contexto Completo**: El script recupera todos los episodios de tu base de datos local.
- **Prompt Inteligente**: Se envía a Gemini tu pregunta junto con los títulos y descripciones de los episodios como contexto.
- **Respuesta Basada en Datos**: La IA tiene la instrucción estricta de responder **únicamente** con la información encontrada en tus podcasts, evitando inventar datos. Si no encuentra nada, te lo dirá.

### Ejemplo de Uso
Si ejecutas:
```bash
python spotify_podcast_extractor.py -q "¿Qué episodios hablan del poder del silencio en la comunicación?"
```

## 🗃️ Base de Datos

### Estructura
El script crea automáticamente `spotify_podcasts.db` con:

- **Tabla `podcasts`**: Información de episodios
- **Tabla `playlists`**: Control de sincronización
- **Evita duplicados**: Solo procesa episodios nuevos
- **Persistente**: Los datos se mantienen entre ejecuciones

### Ventajas
- ⚡ **Ejecuciones rápidas**: Solo procesa contenido nuevo
- 💰 **Ahorra API calls**: Tanto de Spotify como de Gemini
- 📈 **Historial completo**: Mantiene registro de todos los episodios procesados

## 🔧 Argumentos de Línea de Comandos

```bash
# Ayuda completa
python spotify_podcast_extractor.py --help

# Argumentos principales
-p, --playlist PLAYLIST_ID    # Playlist específica a procesar
--categorize-only             # Solo categorizar pendientes  
--export-only                 # Solo exportar a Excel
--no-llm                      # Desactivar Gemini AI
--reset-db                    # Eliminar base de datos
-o, --output FILENAME         # Nombre de archivo Excel
--playlist-id-for-export ID   # Exportar solo una playlist
```

## 📁 Estructura del Proyecto

```
spotify-podcast-extractor/
├── spotify_podcast_extractor.py  # Script principal
├── requirements.txt               # Dependencias Python  
├── .env.example                  # Plantilla de configuración
├── .env                         # Tu configuración (no se sube a Git)
├── .gitignore                   # Archivos ignorados por Git
├── .spotipyoauthcache           # Cache OAuth (generado automáticamente)
├── spotify_podcasts.db          # Base de datos SQLite (generada)
└── README.md                    # Esta documentación
```

## 📋 Archivos Generados

### Archivo Excel
- **Nombre automático**: `spotify_podcasts_PLAYLIST_ID_YYYYMMDD_HHMMSS.xlsx`
- **Formato profesional**: Columnas auto-ajustadas, fechas formateadas
- **Datos ordenados**: Por fecha de agregado (más reciente primero)

### Base de Datos SQLite
- **Archivo**: `spotify_podcasts.db`
- **Portable**: Puedes copiarlo, respaldarlo o inspeccionarlo con cualquier herramienta SQLite

## 🛠️ Solución de Problemas

### 🔑 Problemas de Autenticación
```bash
# Error: Token expirado
rm .spotipyoauthcache
python spotify_podcast_extractor.py  # Vuelve a autenticar
```

### 🤖 Problemas con Gemini AI
```bash
# Error: Cuota excedida
python spotify_podcast_extractor.py --no-llm  # Omitir IA

# Error: API key inválida
# Verifica GEMINI_API_KEY en .env
```

### 📊 Base de Datos Corrupta
```bash
# Resetear completamente
python spotify_podcast_extractor.py --reset-db
```

### 🎵 Playlist Vacía
- Verifica que la playlist contenga **episodios de podcast**, no música
- Comprueba que el `PLAYLIST_ID` sea correcto

### 🔐 Permisos Insuficientes
Asegúrate de que tu app Spotify tenga los scopes:
- `playlist-read-private`
- `playlist-read-collaborative`

## 📊 Estadísticas

Al finalizar, el script muestra:
- **Total de episodios** en base de datos
- **Top 5 categorías** más populares
- **Episodios procesados** en esta ejecución

## 🤝 Contribuciones

¡Las contribuciones son bienvenidas!

1. **Fork** el proyecto
2. **Crea** una rama para tu feature: `git checkout -b feature/amazing-feature`
3. **Commit** tus cambios: `git commit -m 'Add amazing feature'`
4. **Push** a la rama: `git push origin feature/amazing-feature`
5. **Abre** un Pull Request

## 📝 Licencia

MIT License - ver archivo `LICENSE` para detalles.

## 🔒 Seguridad y Privacidad

### ⚠️ Importantes Recordatorios
- **Nunca subas** tu archivo `.env` a Git
- **Nunca compartas** tus credenciales de Spotify o Gemini
- **Revisa** el archivo `.gitignore` para protección automática

### 🔐 Datos Locales
- Toda la información se almacena **localmente** en tu máquina
- **No se envía** información a terceros (excepto APIs de Spotify/Gemini)
- **Controlas completamente** tus datos

## 🆘 Soporte

### Recursos Útiles
- [Documentación Spotify API](https://developer.spotify.com/documentation/)
- [Gemini AI Pricing](https://ai.google.dev/pricing)
- [Issues en GitHub](https://github.com/tu-usuario/spotify-podcast-extractor/issues)

### Logs y Debugging
El script proporciona logs detallados para facilitar el diagnóstico de problemas.

---

**¡Disfruta organizando tus podcasts de Spotify con inteligencia artificial! 🎧🤖**