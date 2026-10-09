"""Alpha Surface: options and market analytics on live tastytrade data.

collector  pulls from providers and writes through to storage
storage    Parquet files with DuckDB views over them
derive     the analytics, pure functions of frames and floats
present    the Streamlit app
"""
