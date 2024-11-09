from fastapi import FastAPI, HTTPException, File, UploadFile
from fastapi.responses import JSONResponse
import os
import requests
import json
import pandas as pd
import time
from azure.cognitiveservices.vision.computervision import ComputerVisionClient
from azure.cognitiveservices.vision.computervision.models import OperationStatusCodes
from msrest.authentication import CognitiveServicesCredentials
from typing import List
import time

app = FastAPI()

API_KEY = "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"
subscription_key = "9VyengLPTp5sLNQQms00PWUkAjUI7rZKX2p1UmPJspRkPxQ07DANJQQJ99AKACqBBLyXJ3w3AAAFACOGPbfr"
endpoint = "https://my-ocr-image.cognitiveservices.azure.com/"
computervision_client = ComputerVisionClient(endpoint, CognitiveServicesCredentials(subscription_key))

AVAILABLE_MODELS = {
    'gpt-4': 'gpt-4',
    'gpt-3.5': 'gpt-3.5-turbo'
}
DEFAULT_MODEL = 'gpt-4'

start_time_ai = 0
start_time_ocr = 0
end_time_ai = 0
end_time_ocr = 0
def get_openai_response(prompt, model_name=DEFAULT_MODEL):

    headers = {
        'Authorization': f'Bearer {API_KEY}',
        'Content-Type': 'application/json',
    }
    data = {
        'model': AVAILABLE_MODELS[model_name],
        'messages': [{'role': 'user', 'content': prompt}],
        'max_tokens': 1500,
        'temperature': 0.5
    }
    try:
        response = requests.post('https://api.openai.com/v1/chat/completions', headers=headers, json=data)
        response.raise_for_status()
        return response.json()['choices'][0]['message']['content']
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 429:  # Rate limit error
            print("Rate limit exceeded. Stopping the process.")
            raise Exception("Rate limit exceeded. Stopping the process.")
        else:
            print(f"HTTP error occurred: {e}")
            raise
    except requests.exceptions.RequestException as e:
        print(f"Error during API request: {e}")
        raise

def process_invoices(invoice_texts, model_name=DEFAULT_MODEL):
    all_data = []
    if model_name not in AVAILABLE_MODELS:
        print(f"Error: Model '{model_name}' is not available. Using default model '{DEFAULT_MODEL}' instead.")
        model_name = DEFAULT_MODEL
    for ocr_output in invoice_texts:
        # Print OCR text for debugging purposes
        print("OCR Output:", ocr_output)
        
        prompt = f"""
        The following text is extracted from an invoice:
        {ocr_output}

        Please extract the following information and provide it in a structured JSON format with the fields:
        - invoice_number: The unique invoice number, usually labeled with "Invoice No."
        - invoice_date: Date of the invoice, usually labeled as "Invoice Date"
        - vendor_name: The seller or supplier name, typically found before "GSTIN" or at the top of the invoice.
        - vendor_address: The address of the vendor.
        - vendor_gst: GST Identification Number (GSTIN) of the vendor, usually labeled with "GST No." or "GSTIN."
        - vendor_pan: PAN (Permanent Account Number) of the vendor if available.
        - buyer_name: The name of the buyer or recipient, typically following "Ship to" or "Buyer".
        - buyer_gst: GST Identification Number of the buyer.
        - shipping_address: Address to which the goods or services are being shipped.
        - site_name: Site or project name where services/goods are provided, if applicable.
        - line_items: Extract line items (as an array of objects) containing:
            - description: Description of the product or service.
            - hsn_sac_code: HSN or SAC code associated with the item.
            - quantity: Quantity of items or services, usually a numeric value followed by units like "CUM", "KG", etc.
            - cumulative_quantity: The cumulative quantity value, usually labeled as "Cumulative Qty" or similar.
            - rate: Rate per unit, usually a monetary value in ₹ (INR). Avoid taking cumulative quantity values as rates.
            - amount: Total amount for the line item.
        - tax_details: An array of objects containing tax details:
            - tax_type: Type of tax (CGST, SGST, IGST, etc.)
            - rate: Tax rate in percentage.
            - amount: Amount of tax charged.
        - total_amount: Total amount payable after all taxes.
        - other_charges: Any additional charges such as transport or handling charges.
        - other_charges_amount: The amount for other charges.

        Important:
        - Ensure that "Vendor" and "Buyer" details are not confused. Vendor is the seller, typically mentioned first, and is associated with "GSTIN" or "PAN".
        - Avoid confusing cumulative quantities with rates. Quantities are usually numeric values with units like "CUM", "KG", or "L". Rates are monetary values with currency symbols like "₹" or "$".
        - If any fields are not found, return "not found" as the value.
        """
        response_content = get_openai_response(prompt, model_name)
        if not response_content:
            continue
        try:
            invoice_data = json.loads(response_content)
        except json.JSONDecodeError:
            print("Error: Could not parse the response as JSON.")
            print("Response:", response_content)
            continue
        if isinstance(invoice_data, str):
            print("Error: Unexpected response format. Response was a string instead of JSON.")
            print("Response:", invoice_data)
            continue

        # Extract summary data with checks for missing details
        summary_data = {
            "Invoice Number": invoice_data.get("invoice_number", "not found"),
            "Invoice Date": invoice_data.get("invoice_date", "not found"),
            "Vendor Name": invoice_data.get("vendor_name", "not found"),
            "Vendor Address": invoice_data.get("vendor_address", "not found"),
            "Vendor GST": invoice_data.get("vendor_gst", "not found"),
            "Vendor PAN": invoice_data.get("vendor_pan", "not found"),
            "Buyer GST": invoice_data.get("buyer_gst", "not found"),
            "Shipping Address": invoice_data.get("shipping_address", "not found"),
            "Site/Project Name": invoice_data.get("site_name", "not found"),
            "Total Amount": invoice_data.get("total_amount", "not found"),
            "Other Charges": invoice_data.get("other_charges", "not found"),
            "Other Charges Amount": invoice_data.get("other_charges_amount", "not found")
        }

        # Handle tax details if available
        tax_details = invoice_data.get("tax_details", [])
        if isinstance(tax_details, list):
            for i, tax in enumerate(tax_details):
                if isinstance(tax, dict):
                    summary_data[f"Tax Type {i+1}"] = tax.get("tax_type", "not found")
                    summary_data[f"Tax Rate {i+1} (%)"] = tax.get("rate", "not found")
                    summary_data[f"Tax Amount {i+1}"] = tax.get("amount", "not found")

        # Handle line items if available
        line_items = invoice_data.get("line_items", [])
        if isinstance(line_items, list):
            for i, item in enumerate(line_items, start=1):
                if isinstance(item, dict):
                    summary_data[f"Description {i}"] = item.get("description", "not found")
                    summary_data[f"HSN/SAC Code {i}"] = item.get("hsn_sac_code", "not found")
                    summary_data[f"Quantity {i}"] = item.get("quantity", "not found")
                    summary_data[f"Cumulative Quantity {i}"] = item.get("cumulative_quantity", "not found")
                    summary_data[f"Rate {i}"] = item.get("rate", "not found")
                    summary_data[f"Amount {i}"] = item.get("amount", "not found")

        all_data.append(summary_data)

    return pd.DataFrame(all_data)

# Function to extract text from image using Azure OCR
def extract_text_from_image(image_path):
    with open(image_path, "rb") as image_stream:
        read_response = computervision_client.read_in_stream(image=image_stream, raw=True)

    read_operation_location = read_response.headers["Operation-Location"]
    operation_id = read_operation_location.split("/")[-1]

    while True:
        read_result = computervision_client.get_read_result(operation_id)
        if read_result.status not in ['notStarted', 'running']:
            break
        time.sleep(1)

    full_text = ""
    if read_result.status == OperationStatusCodes.succeeded:
        for text_result in read_result.analyze_result.read_results:
            for line in text_result.lines:
                full_text += line.text + "\n"
    return full_text.strip()

@app.post("/upload-invoice")
async def upload_invoice(file: UploadFile = File(...)):
    try:
        os.makedirs('uploads', exist_ok=True)
        file_location = f"uploads/{file.filename}"
        print("Upload done")
        with open(file_location, "wb") as f:
            f.write(await file.read())
        start_time_ocr = time.time()
        invoice_text = extract_text_from_image(file_location)
        end_time_ocr = time.time()
        if invoice_text:
            print("Text extracted successfully.")
            invoice_data = process_invoices([invoice_text])
            if invoice_data.empty:
                raise HTTPException(status_code=400, detail="No valid data extracted from the image.")
            print("Invoice data extracted successfully.")
            print(invoice_data)
            invoice_data_dict = invoice_data.to_dict(orient="records")
            return JSONResponse(content={"invoice_data": invoice_data_dict})
        else:
            raise HTTPException(status_code=400, detail="No text extracted from the image.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred during processing: {e}")

@app.get("/")
async def root():
    return {"message": "Welcome to the BluOrgin AI's Invoice Application Processor! add /upload-invoice to the URL to upload an invoice image."}
