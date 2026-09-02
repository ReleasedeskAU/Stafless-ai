# Build POST /search-settings/set-new-search-settings body from GET current.
# SearchSettingsCreationRequest requires index_name. Match server default:
# danswer_chunk_{clean_model_name(model)} (search_nlp_models.clean_model_name).
.model_name = $m
| .model_dim = $d
| .normalize = false
| .query_prefix = ""
| .passage_prefix = ""
| .provider_type = "openai"
| .enable_contextual_rag = false
| .contextual_rag_model_configuration_id = null
| del(.id, .use_port_flow, .api_key)
| .index_name = ("danswer_chunk_" + ($m | gsub("[/.-]"; "_") | ascii_downcase))
