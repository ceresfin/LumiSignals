def log_to_airtable(table, record: dict):
    """
    Sends a single OANDA trade or order record to your Airtable base.
    
    Args:
        table (pyairtable.Table): Airtable table connection object.
        record (dict): Dictionary with fields matching your Airtable schema.
    
    Returns:
        str or None: Airtable record ID if successful, None if failed.
    """
    try:
        response = table.create(record)
        print("✅ Airtable record created:", response["id"])
        return response["id"]
    except Exception as e:
        print("❌ Failed to create Airtable record:", e)
        return None


from pyairtable import Api

def get_airtable_table(api_key, base_id, table_name):
    api = Api(api_key)
    return api.table(base_id, table_name)
