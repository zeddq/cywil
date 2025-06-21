import fitz
import sys
import openai
import os
from pathlib import Path
import asyncio
import json
import re
import functools
from typing import List, Coroutine, Callable, Any, Dict
from pydantic import BaseModel

class Template(BaseModel):
    name: str
    category: str
    variables: list[str]
    template: str


# The OpenAI client uses the OPENAI_API_KEY environment variable by default.
# Make sure it is set in your environment.
client = openai.AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

async def combine_results(pages_coroutine_factories: List[Callable[[], Coroutine[Any, Any, Template]]]) -> Dict[str, Any]:
    combined_result = {}
    results = await asyncio.gather(*(f() for f in pages_coroutine_factories))
    for page_number, obj in enumerate(results):
        print(obj.model_dump())
        combined_template = combined_result.get('template', "") + f"Page {page_number+1}\n" + obj.template
        combined_variables = combined_result.get('variables', []) + obj.variables
        combined_category = combined_result.get('category', "") or obj.category
        combined_result = {
            'variables': combined_variables,
            'category': combined_category,
            'template': combined_template
        }
    return combined_result

async def send_to_openai(full_text):
    print("\n--- Calling OpenAI Chat Completion ---\n")
    try:
        # Feel free to change the model and the prompt.
        completion = await client.responses.parse(
            model="o3-mini",  # or "gpt-3.5-turbo"
            input=[
                {"role": "system", "content": """You are a legal-form parser. User sends you a template form page. Return JSON with:
 - name of the template
 - category of the template (pozew, wezwanie, umowa, etc.)
 - variables [Powod, Pozwany, ...] extracted from provided page
 - template input page back but with [[KeyName]] instead of placeholders to make it easy to substitute later"""},
                {"role": "user", "content": full_text}
            ],
            text_format=Template,
        )

        print("--- OpenAI Response ---\n")
        return completion.output_parsed

    except openai.APIConnectionError as e:
        print(f"Failed to connect to OpenAI API: {e}", file=sys.stderr)
    except openai.RateLimitError as e:
        print(f"OpenAI API request exceeded rate limit: {e}", file=sys.stderr)
    except openai.APIError as e:
        print(f"OpenAI API returned an API Error: {e}", file=sys.stderr)
    except Exception as e:
        print(f"An unexpected error occurred: {e}", file=sys.stderr)
    finally:
        print("\n--- End of OpenAI Response ---\n")


async def main():
    templates_dir = Path("data/pdfs/templates")
    pdf_files = list(templates_dir.glob("*.pdf"))

    pending_calls: List[Coroutine[Any, Any, Dict[str, Any]]] = []
    for file_path in pdf_files:
        print(f"Processing {file_path}")
        pages_call: List[Callable[[], Coroutine[Any, Any, Template]]] = []
        try:
            doc = fitz.open(file_path)
            for page in doc:
                text = page.get_text("text", flags=1)
                print("\n--- Extracted Text ---\n")
                print(text)
                print("\n--- End of Extracted Text ---\n")
                pages_call.append(functools.partial(send_to_openai, text))

        except Exception as e:
            print(f"Error opening PDF file: {e}")
        finally:
            pending_calls.append(combine_results(pages_call))
            doc.close()

    results = await asyncio.gather(*pending_calls)
    for file_path, combined_results in zip(pdf_files, results):
        combined_results['name'] = file_path.stem.replace(' ', '_').lower()
        with open(file_path.with_suffix(".json"), "w", encoding="utf-8") as f: 
            f.write(json.dumps(combined_results, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    asyncio.run(main())
