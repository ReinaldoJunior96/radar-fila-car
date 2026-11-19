# Segurança

Relate vulnerabilidades em particular aos mantenedores do projeto, sem abrir issue pública, com passos para reproduzir e impacto esperado.

- A API é somente leitura para visitantes.
- O índice guarda atributos públicos, sem geometrias e sem dados pessoais adicionados pelo projeto.
- Senhas ficam em variáveis de ambiente e nunca devem ser versionadas.
- `EMBED_ORIGINS` deve listar apenas os sites autorizados.
- Em produção, publique só o proxy e mantenha banco e rotina de sincronização em rede interna.
