Base fictícia para dashboard de Inadimplência por Obra

Arquivos:
1) fato_inadimplencia.csv
2) dim_obras.csv
3) dim_clientes.csv
4) dim_faixa_atraso.csv

Relacionamentos sugeridos:
- fato_inadimplencia[obra_id] -> dim_obras[obra_id]
- fato_inadimplencia[cliente_id] -> dim_clientes[cliente_id]
- fato_inadimplencia[faixa_id] -> dim_faixa_atraso[faixa_id]

Campos importantes para o dashboard:
- Valor atrasado: valor_atrasado
- Quantidade de títulos: titulo_id (distinctcount)
- Tempo médio de inadimplência: dias_atraso
- Evolução mensal: ano_mes
- Tipo: tipo

