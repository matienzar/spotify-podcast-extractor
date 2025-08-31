# Spotify Podcast Extractor


Extrae información detallada de podcasts de tus playlists de Spotify y la exporta a Excel.

## Características

- ✅ Extrae título, descripción, duración de episodios
- ✅ Información del podcast (nombre, descripción)
- ✅ Fecha de publicación y fecha de agregado a playlist
- ✅ URLs de Spotify e imágenes
- ✅ Exporta a Excel con formato automático
- ✅ Soporte para OAuth y tokens temporales
- ✅ Variables de entorno para seguridad

## Requisitos

- Python 3.7+
- Cuenta de Spotify
- App registrada en Spotify Developer Dashboard

## Instalación

1. **Clona el repositorio:**
```bash
git clone https://github.com/tu-usuario/spotify-podcast-extractor.git
cd spotify-podcast-extractor
```

2. **Instala las dependencias:**
```bash
pip install -r requirements.txt
```

3. **Configura las variables de entorno:**
```bash
cp .env.example .env
```

4. **Edita el archivo `.env`** con tus credenciales (ver configuración abajo)

## Configuración

### 1. Crear App en Spotify

1. Ve a [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)
2. Crea una nueva aplicación
3. En "Redirect URIs" añade: `https://example.com/callback`
4. Copia el `Client ID` y `Client Secret`

### 2. Obtener ID de Playlist

1. Ve a tu playlist en Spotify
2. Copia la URL (ej: `https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M`)
3. El ID es la parte final: `37i9dQZF1DXcBWIGoYBM5M`

### 3. Configurar .env

Edita el archivo `.env` con tus valores reales:

```bash
SPOTIFY_CLIENT_ID=tu_client_id_real
SPOTIFY_CLIENT_SECRET=tu_client_secret_real  
SPOTIFY_REDIRECT_URI=https://example.com/callback
SPOTIFY_PLAYLIST_ID=tu_playlist_id_real
```

## Uso

```bash
python spotify_podcast_extractor.py
```

### Primera ejecución (OAuth):

1. El script abrirá tu navegador automáticamente
2. Inicia sesión en Spotify y autoriza la aplicación
3. Spotify te redirigirá a `https://example.com/callback?code=...`
4. La página dirá "no encontrada" - ¡es normal!
5. Copia la URL completa de la barra de direcciones
6. Pégala en la terminal cuando te lo pida
7. ¡Listo! El script guardará las credenciales para futuros usos

### Salida

El script genera un archivo Excel con nombre automático:
- `spotify_podcasts_YYYYMMDD_HHMMSS.xlsx`
- Contiene toda la información de los episodios
- Ordenado por fecha de agregado a la playlist

## Estructura del Proyecto

```
spotify-podcast-extractor/
├── spotify_podcast_extractor.py  # Script principal
├── requirements.txt               # Dependencias Python
├── .env.example                  # Plantilla de configuración
├── .env                         # Tu configuración (no se sube a Git)
├── .gitignore                   # Archivos ignorados por Git
└── README.md                    # Esta documentación
```

## Datos Extraídos

Para cada episodio de podcast:

- **Título del episodio**
- **Descripción del episodio** 
- **Nombre del podcast**
- **Descripción del podcast**
- **Duración** (en ms y minutos)
- **Fecha de publicación**
- **Fecha de agregado a la playlist** ⭐
- **URL de Spotify**
- **URL de imagen**
- **Idioma**
- **Contenido explícito**

## Solución de Problemas

### Token expirado
Si usas un token temporal, genera uno nuevo en:
https://developer.spotify.com/console/get-playlist-tracks/

### Playlist vacía o sin podcasts
Verifica que tu playlist contenga episodios de podcast, no música.

### Error de permisos
Asegúrate de que tu aplicación tenga los scopes:
- `playlist-read-private`
- `playlist-read-collaborative`

## Contribuciones

¡Las contribuciones son bienvenidas! Por favor:

1. Fork el proyecto
2. Crea una rama para tu feature
3. Commit tus cambios
4. Push a la rama
5. Abre un Pull Request

## Licencia

MIT License - ver archivo LICENSE para detalles

## Seguridad

⚠️ **Nunca subas tu archivo `.env` a Git**
⚠️ **Nunca compartas tus credenciales de Spotify**

El archivo `.gitignore` está configurado para proteger tus credenciales automáticamente.