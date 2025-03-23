from datetime import datetime, timezone

def normalize_datetime_comparison(dt1, dt2):
    """
    Normaliza dos objetos datetime para que ambos sean comparables.
    Si uno tiene zona horaria (aware) y el otro no (naive), 
    convierte el naive a aware usando la zona horaria del otro.
    Si ambos son naive, los mantiene así.
    Si ambos son aware pero con diferentes zonas horarias, los convierte a UTC.
    
    Args:
        dt1 (datetime): Primer objeto datetime
        dt2 (datetime): Segundo objeto datetime
        
    Returns:
        tuple: (dt1_normalized, dt2_normalized)
    """
    # Si ambos son naive o ambos son aware con la misma zona horaria
    if (dt1.tzinfo is None and dt2.tzinfo is None) or \
       (dt1.tzinfo is not None and dt2.tzinfo is not None and dt1.tzinfo == dt2.tzinfo):
        return dt1, dt2
    
    # Si dt1 es aware pero dt2 es naive
    if dt1.tzinfo is not None and dt2.tzinfo is None:
        dt2 = dt2.replace(tzinfo=dt1.tzinfo)
        return dt1, dt2
    
    # Si dt2 es aware pero dt1 es naive
    if dt2.tzinfo is not None and dt1.tzinfo is None:
        dt1 = dt1.replace(tzinfo=dt2.tzinfo)
        return dt1, dt2
    
    # Si ambos son aware pero con diferentes zonas horarias, convertir a UTC
    if dt1.tzinfo is not None and dt2.tzinfo is not None and dt1.tzinfo != dt2.tzinfo:
        dt1 = dt1.astimezone(timezone.utc)
        dt2 = dt2.astimezone(timezone.utc)
        return dt1, dt2
    
    # Este caso no debería ocurrir, pero por si acaso
    return dt1, dt2