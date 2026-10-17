#!/usr/bin/env python3
"""Warm the TensorFlow Hub cache by loading YAMNet once."""

import tensorflow_hub as hub


if __name__ == "__main__":
    model = hub.load("https://tfhub.dev/google/yamnet/1")
    print(f"YAMNet loaded: {model}")
