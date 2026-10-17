# Azure Setup Guide

Step-by-step setup for the Azure resources and the Azure DevOps pipeline.
Replace every `<placeholder>` with your own names.

---

## 1. Data source: Blob Storage

1. Create a resource group, e.g. `rg-rag-app` (East US).
2. Create a **Storage account**, e.g. `<yourstorage>`.
3. Create a container, e.g. `travel-docs`.
4. Upload the PDFs from [`data/collateral/`](../data/collateral). You can add your own documents too.

## 2. Azure AI Search: index the documents

1. Create an **Azure AI Search** service. The Free tier is enough for the demo.
2. Choose **Import data** → **Azure Blob Storage**, and select your storage account and container.
3. Scenario: **Keyword search**.
4. **Enrich your data**: enable the skills for key phrases, locations and persons. Attach an Azure AI multi-service account when the wizard asks for one.
5. Review the index fields (`chunk`, `title`, `keyPhrases`, `locations`, `persons`, `metadata_storage_path`).
6. Schedule: **Once** → **Create**.
7. Copy the **endpoint**, a **query key** and the **index name**. They go into `.env` and the ADO variable group.

## 3. Azure OpenAI

1. Create an **Azure AI Foundry** project or an Azure OpenAI resource.
2. Deploy a chat model, e.g. **gpt-4.1**.
3. Copy the **endpoint**, **key** and **deployment name**.

## 4. App Service

| Setting | Value |
|---|---|
| App Service plan | Linux, `B1`/`B2` |
| Web App runtime | Python 3.11 |
| Name | `rag-app-<your-unique-id>` |

Enable **Monitoring → App Service logs → Application logging (Filesystem)** so you can use **Log stream**.

The pipeline sets the startup command and app settings, so you don't need to configure them manually.

## 5. Azure DevOps

### Service connection
**Project settings → Service connections → New → Azure Resource Manager**
- Authentication: **Workload identity federation (automatic)**. This is the recommended option because no secrets are stored.
- Scope: resource group `rg-rag-app`
- Name: `azure-service-connection`

### Variable group
**Pipelines → Library → + Variable group** → `rag-app-settings`

| Variable | Secret |
|---|---|
| `SEARCH_SERVICE_ENDPOINT` | |
| `SEARCH_SERVICE_QUERY_KEY` | 🔒 |
| `SEARCH_INDEX_NAME` | |
| `AZURE_OPENAI_ENDPOINT` | |
| `AZURE_OPENAI_KEY` | 🔒 |
| `AZURE_OPENAI_DEPLOYMENT` | |

### Environment
**Pipelines → Environments → New** → `production`. Optionally add an **Approvals** check for a manual gate.

### Pipeline
1. **Pipelines → New pipeline** → GitHub (or Azure Repos) → select this repo.
2. ADO detects `azure-pipelines.yml`. Set `webAppName` to your app name.
3. Run it. The pipeline goes Build → Deploy → Smoke test (`/health`).

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `Application Error` after deploy | Wrong startup command or missing packages | Check **Log stream**; make sure `SCM_DO_BUILD_DURING_DEPLOYMENT=true` is set |
| Error page on `/ask` | Wrong key, endpoint or deployment name | Verify the variable group values; check **Log stream** for the exception |
| Search returns nothing | Wrong index name, or the indexer hasn't run | Check the index in the portal; re-run the indexer |
| Deploy stage can't authenticate | Service connection scope or name | Recreate the connection and match `azureSubscription` in the YAML |
| Smoke test times out | App is still warming up on first deploy | Re-run the stage; consider a higher plan tier |

## Security checklist

- 🔒 Never commit `.env`. It's already in `.gitignore`.
- 🔒 Keep keys as **locked** variables, or better, use **Key Vault references**.
- 🔒 Rotate keys if they were ever shared.
- 🔒 Turn on **HTTPS only** on the Web App.
