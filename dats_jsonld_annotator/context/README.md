# DATS JSON-LD context files

This repository contains JSON for Linked Data ([JSON-LD](http://json-ld.org/)) context files for the DAta Tag Suite (DATS) model for describing datasets. These context files provide a semantic framework for DATS JSON files. This means that each of the DATS entities and attributes are mapped to ontology terms, and these mappings are contained in context files. By referencing the context files in the JSON instances, you can obtain linked data in the form of JSON-LD files, which can also be converted to other serializations of the Resource Description Framework ([RDF](https://www.w3.org/RDF/)). 

These context files can be used in combination with the [DATS schemas](https://github.com/datatagsuite/schema) to produce DATS JSON-LD files. The schemas allow to validate the structure of the JSON-LD files. 

We provide context files that map the DATS elements to a set of vocabularies:

- context files mapping to [schema.org](https://schema.org/). 
- context files mapping to the  [OBO Foundry ontologies](http://www.obofoundry.org/)

These context files can be used on their own or in combination between each other. It would also be possible to create context files including schema.org and OBO Foundry ontologies simultaneously, using terms when relevant. At the moment, we chose to provide separate context files for different semantic frameworks, enabling the user to choose what vocabularies to consider.

The schema.org context files are available [here](https://github.com/datatagsuite/context/tree/master/sdo). 

The [OBO Foundry] context files are available [here](https://github.com/datatagsuite/context/tree/master/obo).

The context files can be accessed by persistent identifiers relying on the [w3id.org](http://w3id.org/) service. 

For example, the schema.org-based JSON-LD context file for the dataset entity can be accessed through this URL: http://w3id.org/dats/context/sdo/dataset_sdo_context.jsonld

While the OBO-based JSON-LD context file for the dataset entity can be accessed here:
http://w3id.org/dats/context/obo/dataset_obo_context.jsonld

Consequently, if you want to use the context in a JSON file describing a dataset, you can include it as follows:
```
 {
   "@context": "http://w3id.org/dats/context/sdo/dataset_sdo_context.jsonld"
   ...
```

or 

```
 {
   "@context": "http://w3id.org/dats/context/obo/dataset_obo_context.jsonld"
   ...
```

or 

```
 {
   "@context": ["http://w3id.org/dats/context/sdo/dataset_sdo_context.jsonld",   "http://w3id.org/dats/context/obo/dataset_obo_context.jsonld"]
   ...
```

## License

These context files are distributed under [CC BY-SA 3.0](http://creativecommons.org/licenses/by-sa/3.0/) license.
