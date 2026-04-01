"""
EmailMVP Architecture Diagram
Generates a PNG architecture diagram with official Azure icons.
"""

from diagrams import Diagram, Cluster, Edge
from diagrams.azure.compute import FunctionApps
from diagrams.azure.web import AppServices
from diagrams.azure.storage import BlobStorage
from diagrams.azure.security import KeyVaults
from diagrams.azure.identity import ManagedIdentities
from diagrams.azure.monitor import ApplicationInsights
from diagrams.azure.ml import AzureOpenAI
from diagrams.onprem.client import User

graph_attr = {
    "fontsize": "36",
    "fontname": "Segoe UI Bold",
    "bgcolor": "white",
    "pad": "1.2",
    "nodesep": "1.4",
    "ranksep": "1.6",
    "dpi": "150",
}

node_attr = {
    "fontsize": "15",
    "fontname": "Segoe UI",
}

edge_attr = {
    "fontsize": "13",
    "fontname": "Segoe UI",
    "penwidth": "1.5",
}

cluster_attr = {
    "fontsize": "16",
    "fontname": "Segoe UI Bold",
}

with Diagram(
    "EmailMVP - Cold Email Generation Platform",
    filename="emailmvp_architecture",
    outformat="png",
    show=False,
    direction="LR",
    graph_attr=graph_attr,
    node_attr=node_attr,
    edge_attr=edge_attr,
):
    user = User("Sales Rep\n(Browser)")

    with Cluster("Azure  |  rg-emailmvp-eastus2  |  East US 2", graph_attr=cluster_attr):

        with Cluster("Frontend", graph_attr=cluster_attr):
            swa = AppServices("Static Web App\nazswa...6476")

        with Cluster("Compute  (7 Durable Functions)", graph_attr=cluster_attr):
            func = FunctionApps("Azure Functions\nazfn...6476\nPython 3.11 | EP1")

        with Cluster("AI  (RG: TestFoundary)", graph_attr=cluster_attr):
            openai = AzureOpenAI("Azure OpenAI\ngpt-53-chat\nGPT 5.3 | GlobalStd")

        with Cluster("Data", graph_attr=cluster_attr):
            blob = BlobStorage("Blob Storage\nazst...6476\ncsv-input / csv-output")

        with Cluster("Security", graph_attr=cluster_attr):
            kv = KeyVaults("Key Vault\nazkv...6476")
            mi = ManagedIdentities("Managed Identity\nazid...6476")

        with Cluster("Monitoring", graph_attr=cluster_attr):
            ai = ApplicationInsights("App Insights\nazai...6476")

    # ── Data flow ──
    user >> Edge(label="1. Upload CSV", color="dodgerblue", style="bold", fontsize="13") >> swa
    swa >> Edge(label="2. POST /api/upload", color="dodgerblue", style="bold", fontsize="13") >> func
    func >> Edge(label="3. Store CSV", color="forestgreen", fontsize="13") >> blob
    func >> Edge(label="4. Fan-out x15", color="darkorange", style="bold", fontsize="13") >> openai
    openai >> Edge(label="5. 8 emails/lead", color="darkorange", style="dashed", fontsize="13") >> func
    func >> Edge(label="6. Assemble CSV", color="forestgreen", fontsize="13") >> blob
    blob >> Edge(label="7. Download CSV", color="purple", style="bold", fontsize="13") >> swa
    swa >> Edge(label="8. CSV to user", color="purple", style="bold", fontsize="13") >> user

    # ── Auth & config ──
    mi >> Edge(label="RBAC", color="gray", style="dotted", fontsize="12") >> blob
    mi >> Edge(label="RBAC", color="gray", style="dotted", fontsize="12") >> kv
    func >> Edge(label="Secrets", color="gray", style="dotted", fontsize="12") >> kv
    func >> Edge(label="Logs", color="gray", style="dotted", fontsize="12") >> ai


print("Diagram saved to: emailmvp_architecture.png")
