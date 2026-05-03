"""VoiceNovel Server CLI."""

import argparse

import uvicorn

from vn_server.api import create_app


def main():
    parser = argparse.ArgumentParser(description="VoiceNovel Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind")
    parser.add_argument("--port", type=int, default=5000, help="Port to bind")
    parser.add_argument("--data-dir", default="data", help="Data directory")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload")
    args = parser.parse_args()

    if args.reload:
        uvicorn.run(
            "vn_server.api:create_app",
            host=args.host,
            port=args.port,
            reload=True,
            factory=True,
        )
    else:
        app = create_app(data_dir=args.data_dir)
        uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
