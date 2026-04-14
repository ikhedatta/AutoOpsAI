import re

path = '/home/ec2-user/AutoOpsAI/agent/main.py'
with open(path, 'r') as f:
    content = f.read()

# Add webhook router import after observability import
old_import = 'from agent.api.routes_observability import router as observability_router  # noqa: E402'
new_import = old_import + '\nfrom agent.api.routes_webhook import router as webhook_router  # noqa: E402'

if 'routes_webhook' not in content:
    content = content.replace(old_import, new_import)
    print('Added import')
else:
    print('Import already present')

# Add webhook router registration after observability router
old_include = 'app.include_router(observability_router, prefix="/api/v1")'
new_include = old_include + '\napp.include_router(webhook_router, prefix="/api/v1")'

if 'webhook_router' not in content or 'include_router(webhook_router' not in content:
    content = content.replace(old_include, new_include)
    print('Added include_router')
else:
    print('include_router already present')

with open(path, 'w') as f:
    f.write(content)

print('Done. Verifying:')
for i, line in enumerate(content.split('\n'), 1):
    if 'webhook' in line:
        print(f'  line {i}: {line}')
