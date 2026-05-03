"""VoiceNovel Server entry point."""

import uvicorn

from vn_server.api import create_app


def main():
    app = create_app(data_dir="data")
    uvicorn.run(app, host="0.0.0.0", port=8901)


if __name__ == "__main__":
    main()
