from app import create_app, db
from app.wg.manager import init_server_keys, write_wg_config, restore_port_forward_rules
import os

app = create_app()

if __name__ == '__main__':
    with app.app_context():
        init_server_keys()
        write_wg_config()
        restore_port_forward_rules()

    host = app.config.get('WEB_HOST', '0.0.0.0')
    port = int(os.environ.get('FREEPN_PORT', app.config.get('ADMIN_PORT', 943)))
    app.run(host=host, port=port, debug=False)
