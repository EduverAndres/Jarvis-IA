(function () {
  "use strict";

  // El SDK llama esta función global apenas termina de cargar su propio script.
  window.onSpotifyWebPlaybackSDKReady = () => {
    if (!window.Spotify) return;

    const player = new Spotify.Player({
      name: "JARVIS",
      getOAuthToken: (callback) => {
        pywebview.api.get_spotify_token().then((token) => {
          if (token) callback(token);
        });
      },
      volume: 0.7,
    });

    player.addListener("ready", ({ device_id }) => {
      pywebview.api.set_spotify_device_id(device_id);
    });

    player.addListener("not_ready", () => {
      pywebview.api.set_spotify_device_id(null);
    });

    player.addListener("initialization_error", ({ message }) => {
      pywebview.api.spotify_player_error("no se pudo inicializar: " + message);
    });

    player.addListener("authentication_error", ({ message }) => {
      pywebview.api.spotify_player_error("error de autenticación: " + message);
    });

    player.addListener("account_error", ({ message }) => {
      pywebview.api.spotify_player_error("cuenta sin Premium o sin permiso: " + message);
    });

    // Cada cambio real de reproducción (play, pausa, cambio de canción,
    // salto) — Python decide ahí si hace falta consultar género/tempo o
    // solo reanclar la posición, para no golpear la API de Spotify de más.
    player.addListener("player_state_changed", (state) => {
      if (!state) {
        pywebview.api.spotify_track_changed(null, null, false, 0);
        return;
      }
      const track = state.track_window && state.track_window.current_track;
      const trackId = track ? track.id : null;
      const artistUri = track && track.artists && track.artists[0] ? track.artists[0].uri : null;
      const artistId = artistUri ? artistUri.split(":").pop() : null;
      pywebview.api.spotify_track_changed(trackId, artistId, !state.paused, state.position || 0);
    });

    player.connect();
  };
})();
