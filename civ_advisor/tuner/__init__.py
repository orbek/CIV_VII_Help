"""Reading Civilization VI's live state through its tuner socket.

The socket exists only when the player has set `EnableTuner 1` in the game's
own AppOptions.txt. This package never writes that file -- see the spec's
"The advisor never enables the tuner".
"""
