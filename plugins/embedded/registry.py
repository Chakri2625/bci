def load_subplugins():
    plugins = {}
    
    try:
        from plugins.embedded.subplugins.rc_car.plugin import RcCarPlugin
        plugins['rc_car'] = RcCarPlugin()
    except Exception as e:
        print(f"Error loading rc_car plugin: {e}")
        
    return plugins
