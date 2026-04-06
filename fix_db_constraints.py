import psycopg2
import sys

def drop_foreign_keys(dbname="default", user="odoo19"):
    # Connect to the PostgreSQL database
    try:
        conn = psycopg2.connect(dbname=dbname, user=user)
        cur = conn.cursor()
    except Exception as e:
        print(f"Failed to connect to the database: {e}")
        sys.exit(1)

    # List of constraints to drop
    constraints_to_drop = [
        ("van_trip_line", "van_trip_line_product_id_fkey"),
        ("van_sale_order_line", "van_sale_order_line_product_id_fkey"),
        ("van_pos_order_line", "van_pos_order_line_product_id_fkey"),
        ("van_agent_inventory_line", "van_agent_inventory_line_product_id_fkey")
    ]

    print(f"Connected to database '{dbname}' as user '{user}'.")
    print("Dropping problematic foreign key constraints...\n")

    for table, constraint in constraints_to_drop:
        try:
            # Check if constraint exists before dropping
            cur.execute("""
                SELECT constraint_name 
                FROM information_schema.table_constraints 
                WHERE table_name = %s AND constraint_name = %s;
            """, (table, constraint))
            
            if cur.fetchone():
                cur.execute(f'ALTER TABLE "{table}" DROP CONSTRAINT "{constraint}";')
                print(f"✅ Dropped constraint '{constraint}' from table '{table}'.")
            else:
                print(f"ℹ️ Constraint '{constraint}' does not exist on table '{table}'. Skipping.")
        except Exception as e:
            print(f"❌ Failed to drop constraint for '{table}': {e}")
            conn.rollback()
            continue

    # Commit changes and close
    conn.commit()
    cur.close()
    conn.close()
    
    print("\nDatabase fix completed! You can now restart Odoo to upgrade the module.")

if __name__ == "__main__":
    db_name = sys.argv[1] if len(sys.argv) > 1 else "logistika"
    drop_foreign_keys(dbname=db_name)
