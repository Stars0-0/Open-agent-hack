SYNTHETIC data only. Three insurers hold separate claim tables; three directories add context.
Table names come from env (RB_TABLE_A, RB_TABLE_B, RB_TABLE_C, RB_TABLE_SHOPS, RB_TABLE_ADDRESSES; see .env.example). Defaults match the sample CSV names.

insurer_a_claims, insurer_b_claims, insurer_c_claims   (one silo per insurer, same columns)
    claim_id, claimant_name, phone, address, vin, shop_id, claim_date, amount, narrative
repair_shops        shop_id, name, address, phone, owner
address_directory   address, kind ('house' | 'apartment_block'), unit_count
vehicle_registry    vin, registered_owner, make
