import os
import sys
import time
import uuid
import json
import psycopg2
from psycopg2.extras import RealDictCursor
from src.usg_model_builder import run_simulation

DB_URL = os.environ.get("DATABASE_URL")
if not DB_URL:
    print("WARNING: DATABASE_URL not set. Running in dry-run mode.")
    sys.exit(0)

def process_queue():
    """
    Connect to PostgreSQL and poll for jobs.
    If no jobs are found, exit(0) to allow Render to scale to zero.
    """
    try:
        conn = psycopg2.connect(DB_URL)
        conn.autocommit = False
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        while True:
            # 1. Fetch next job with safe row-locking
            cursor.execute("SELECT * FROM get_next_queued_job('worker_1')")
            job = cursor.fetchone()
            
            if not job:
                print("Queue is empty. Exiting to allow scale-to-zero.")
                break
                
            job_id = job['job_id']
            payload = job['job_payload']
            company_id = job['job_company_id']
            project_code = job['job_project_code']
            
            print(f"Processing job {job_id} for company {company_id}, project {project_code}")
            
            try:
                # 2. Pre-flight verification (Credit Check)
                cursor.execute("SELECT credit_balance FROM company_wallets WHERE id = %s FOR UPDATE", (company_id,))
                wallet = cursor.fetchone()
                
                if not wallet or wallet['credit_balance'] <= 0:
                    raise Exception("INSUFFICIENT_CREDITS")
                
                # 3. Run Simulation Engine
                ok, summary, outdir = run_simulation("", payload)
                
                if not ok:
                    raise Exception(summary.get("error", "Unknown error during simulation"))
                
                # 4. Atomic Deduction & Audit Trail
                cursor.execute("UPDATE company_wallets SET credit_balance = credit_balance - 1, updated_at = NOW() WHERE id = %s", (company_id,))
                
                # Fetch user_id for the ledger (assuming it's in the payload or job table)
                # For this script, we'll fetch it from the original job record
                cursor.execute("SELECT user_id FROM simulation_jobs WHERE id = %s", (job_id,))
                user_id = cursor.fetchone()['user_id']
                
                cursor.execute("""
                    INSERT INTO credit_ledger (company_id, user_id, project_code, credits_used)
                    VALUES (%s, %s, %s, 1)
                """, (company_id, user_id, project_code))
                
                # 5. Mark Job Completed
                cursor.execute("""
                    UPDATE simulation_jobs 
                    SET status = 'completed', result = %s, updated_at = NOW() 
                    WHERE id = %s
                """, (json.dumps(summary), job_id))
                
                conn.commit()
                print(f"Job {job_id} completed successfully. Credit deducted.")
                
            except Exception as e:
                conn.rollback()
                err_msg = str(e)
                print(f"Job {job_id} failed: {err_msg}")
                
                # Mark job as failed
                try:
                    cursor.execute("""
                        UPDATE simulation_jobs 
                        SET status = 'failed', error_message = %s, updated_at = NOW() 
                        WHERE id = %s
                    """, (err_msg, job_id))
                    conn.commit()
                except Exception as rollback_err:
                    print(f"Failed to update job {job_id} status to failed: {rollback_err}")
                    conn.rollback()

    except Exception as e:
        print(f"Worker crashed: {e}")
        sys.exit(1)
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    process_queue()
