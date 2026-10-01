"""Convert the existing ExamHub records to the new exam format.

    python -m examhub_pipeline.convert text      # fetched files -> page text + tables
    python -m examhub_pipeline.convert extract   # text -> new-format records
    python -m examhub_pipeline.convert score     # compare with the hand-built golden set

The documents come from ``scrapy crawl records``.
"""
