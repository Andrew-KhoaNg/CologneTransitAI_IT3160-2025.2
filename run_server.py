import sys

sys.path.insert(0, "backend")

import app as backend_app


if __name__ == "__main__":
    backend_app.app.run(debug=False, port=5000)
