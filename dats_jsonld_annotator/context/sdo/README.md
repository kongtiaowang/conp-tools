This folder contains the context files for mapping DATS to the [schema.org](https://schema.org) vocabulary.

The mapping is an approximation, as [schema.org](https://schema.org) coverage is quite generic at the moment and terms in the DATS extension for biomedical datasets, such as ```TaxonomicInformation``` are not covered. Other biomedical terms are somewhat covered by the [schema.org healthcare and life science extension](https://health-lifesci.schema.org/). For example, ```DATS:Disease``` has been mapped to [```sdo:MedicalCondition```](https://health-lifesci.schema.org/MedicalCondition).

Some specific comments:
- In DATS, [date information](https://github.com/datatagsuite/schema/blob/master/date_info_schema.json) is represented with a ```date``` that can be qualified by its ```type```, however in [schema.org](https://schema.org)  specific properties are given for different types of date (see [DateTime](https://schema.org/DateTime)). 
 