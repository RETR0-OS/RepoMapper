# Argus

Argus is a HydraDB-backed VS Code view of your current project. It shows bounded repository structure, exact source evidence, traces, observable agent activity, graph changes, and saved system lenses.

Normal installation is plug-and-play:

1. Open a local project folder in VS Code.
2. Run **Argus: Set Up Argus**.
3. Select or create a HydraDB account profile.
4. Enter the API key and this project's database in masked fields.
5. Let Argus test read access.
6. Review and confirm the initial index.

The extension starts its bundled local service automatically. Python, Node.js, terminal commands, environment variables, and a separate MCP process are not required.

API keys and database names are stored through VS Code SecretStorage. They are retrieved for one HydraDB operation at a time and are never placed in settings, process arguments, environment variables, webviews, or MCP configuration.

See the [full project documentation](https://github.com/RETR0-OS/Argus/tree/main/docs) for views, workflows, trust boundaries, Compare, Preserve, Observe, and agent setup.

This release supports local VS Code desktop on Windows, macOS, and glibc Linux for x64 and ARM64. Remote extension hosts, VS Code Web, Codespaces, WSL-hosted extension processes, Alpine, and ARMHF are not supported.
