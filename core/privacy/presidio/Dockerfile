FROM mcr.microsoft.com/presidio-analyzer:latest
COPY nlp.yaml /app/presidio_analyzer/conf/amadeus_nlp.yaml
RUN python -m spacy download de_core_news_md \
 && sed -i 's/^supported_languages: *$/supported_languages:\n  - de/' presidio_analyzer/conf/default_analyzer.yaml \
 && sed -i '0,/^  - en$/s//  - en\n  - de/' presidio_analyzer/conf/default_recognizers.yaml
ENV NLP_CONF_FILE=presidio_analyzer/conf/amadeus_nlp.yaml
