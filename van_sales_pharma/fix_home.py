import sys

def update_home_action(env):
    action = env.ref('van_sales_pharma.action_van_mobile_pos_entry', raise_if_not_found=False)
    if not action:
        print("Action not found")
        return
        
    agents_group = env.ref('van_sales_pharma.group_van_agent', raise_if_not_found=False)
    if not agents_group:
        print("Agent group not found")
        return
        
    for user in agents_group.users:
        if not user.has_group('van_sales_pharma.group_van_admin') and not user.has_group('base.group_system'):
            user.action_id = action.id
            
    env.cr.commit()
    print("Agent home actions successfully updated!")

update_home_action(env)
