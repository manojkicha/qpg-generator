import asyncio
from app.services.pdf_rendering_service import PDFRenderingService

async def test():
    try:
        renderer = PDFRenderingService()
        # Minimal JSON to test rendering
        paper = {"title": "Test Paper", "questions": []}
        answer = {"job_id": "test_job", "answers": []}
        
        print("Testing question paper render...")
        q_pdf = await renderer.render_question_paper(paper)
        print(f"Question paper rendered: {len(q_pdf)} bytes")
        
        print("Testing answer key render...")
        a_pdf = await renderer.render_answer_key(answer)
        print(f"Answer key rendered: {len(a_pdf)} bytes")
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test())
