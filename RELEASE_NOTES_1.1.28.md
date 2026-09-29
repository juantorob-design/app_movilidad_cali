# Release 1.1.28

## Descarga

[Instalador de Windows 1.1.28](https://drive.google.com/uc?export=download&id=1CTI8le9e4XiFFjAsdqe9C75JcgFa_VVG)

## Correcciones del flujo documental

- Conserva la familia documental al vincular complementos desde
  `Pendientes/Por_vincular/PLACA` a un expediente.
- Prioriza evidencia positiva de un recurso sobre frases negativas de otras
  partes del expediente, sin clasificar como `Con recurso` los casos que solo
  indican que no se interpuso recurso.
- Evita empaquetar dos veces el editor PDF en el instalador.
- Permite al actualizador descargar instaladores públicos de Google Drive y
  resolver la confirmación requerida por archivos grandes.

## Validación

- Suite completa de pruebas automatizadas: 40/40.
- Compilación de módulos Python y validación de formato del diff correctas.
- El ejecutable empaquetado inicia la interfaz local y responde HTTP 200.
