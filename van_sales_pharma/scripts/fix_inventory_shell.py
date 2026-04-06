env['van.agent.inventory.line'].search([]).unlink()
trips = env['van.trip'].search([('state', 'in', ['validated', 'in_progress'])])
count = 0
for trip in trips:
    summary = env['van.agent.summary'].search([('agent_id', '=', trip.agent_id.id)], limit=1)
    if summary:
        for line in trip.trip_line_ids:
            if line.loaded_qty > 0:
                inv_line = env['van.agent.inventory.line'].search([
                    ('summary_id', '=', summary.id),
                    ('product_id', '=', line.product_id.id)
                ], limit=1)
                if inv_line:
                    inv_line.loaded_qty += line.loaded_qty
                else:
                    env['van.agent.inventory.line'].create({
                        'summary_id': summary.id,
                        'product_id': line.product_id.id,
                        'price_unit': line.price_unit,
                        'loaded_qty': line.loaded_qty,
                    })
                    count += 1
env.cr.commit()
print(f"SUCCESS: Rebuilt {count} true inventory lines!")
