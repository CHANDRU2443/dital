import time
from datetime import datetime, timedelta
import threading

class Account:
    def __init__(self, account_id, pin, daily_limit=5000.0, large_tx_threshold=2000.0):
        self.account_id = account_id
        self.pin = pin
        self.balance = 0.0
        self.daily_limit = daily_limit
        self.large_tx_threshold = large_tx_threshold
        
        self.history = []  # List of dicts tracking transaction details
        self.failed_pin_attempts = 0
        self.is_locked = False
        self.lock = threading.Lock()

    def verify_pin(self, pin):
        if self.is_locked:
            return False
        if self.pin == pin:
            self.failed_pin_attempts = 0
            return True
        else:
            self.failed_pin_attempts += 1
            if self.failed_pin_attempts >= 3:
                self.is_locked = True
            return False

    def get_daily_spent(self):
        today = datetime.now().date()
        total = 0.0
        for tx in self.history:
            if tx['status'] == 'SUCCESS' and tx['type'] in ['WITHDRAWAL', 'TRANSFER_OUT']:
                tx_date = datetime.fromtimestamp(tx['timestamp']).date()
                if tx_date == today:
                    total += tx['amount']
        return total

    def check_velocity_flag(self):
        # Checks if more than 5 transactions have been attempted/executed in the last 10 minutes
        ten_minutes_ago = time.time() - 600
        recent_txs = [tx for tx in self.history if tx['timestamp'] >= ten_minutes_ago]
        return len(recent_txs) >= 5


class DigitalWalletSystem:
    def __init__(self):
        self.accounts = {}
        self.system_lock = threading.Lock()

    def create_account(self, account_id, pin, daily_limit=5000.0):
        with self.system_lock:
            if account_id in self.accounts:
                return False, "Account already exists."
            if len(str(pin)) < 4:
                return False, "PIN must be at least 4 digits."
            self.accounts[account_id] = Account(account_id, pin, daily_limit)
            return True, "Account created successfully."

    def _detect_fraud(self, account, amount, pin_verified, tx_type):
        flags = []
        
        if account.is_locked or account.failed_pin_attempts >= 3:
            flags.append("MULTIPLE_FAILED_PIN_ATTEMPTS")
            
        if not pin_verified and not account.is_locked:
            # Check if this current failed attempt triggers the threshold
            if account.failed_pin_attempts >= 3:
                flags.append("MULTIPLE_FAILED_PIN_ATTEMPTS")

        if amount > account.large_tx_threshold:
            flags.append("LARGE_TRANSACTION")

        if account.check_velocity_flag():
            flags.append("HIGH_VELOCITY_TRANSACTIONS")

        # Unusual transaction amount: defined here as 5x the user's historical average transaction size
        successful_txs = [tx['amount'] for tx in account.history if tx['status'] == 'SUCCESS']
        if len(successful_txs) >= 3:
            avg_amount = sum(successful_txs) / len(successful_txs)
            if amount > (avg_amount * 5):
                flags.append("UNUSUAL_TRANSACTION_AMOUNT")

        return flags

    def deposit(self, account_id, amount):
        if amount <= 0:
            return False, "Amount must be positive.", []

        with self.system_lock:
            account = self.accounts.get(account_id)
            
        if not account:
            return False, "Account not found.", []

        with account.lock:
            fraud_flags = self._detect_fraud(account, amount, True, 'DEPOSIT')
            
            account.balance += amount
            account.history.append({
                'timestamp': time.time(),
                'type': 'DEPOSIT',
                'amount': amount,
                'status': 'SUCCESS',
                'flags': fraud_flags
            })
            
            msg = "Deposit successful." if not fraud_flags else "Deposit successful (Flagged for review)."
            return True, msg, fraud_flags

    def withdraw(self, account_id, pin, amount):
        if amount <= 0:
            return False, "Amount must be positive.", []

        with self.system_lock:
            account = self.accounts.get(account_id)

        if not account:
            return False, "Account not found.", []

        with account.lock:
            pin_ok = account.verify_pin(pin)
            fraud_flags = self._detect_fraud(account, amount, pin_ok, 'WITHDRAWAL')

            if not pin_ok:
                account.history.append({
                    'timestamp': time.time(),
                    'type': 'WITHDRAWAL',
                    'amount': amount,
                    'status': 'FAILED_PIN',
                    'flags': fraud_flags
                })
                return False, "Invalid PIN or account locked.", fraud_flags

            if account.balance < amount:
                account.history.append({
                    'timestamp': time.time(),
                    'type': 'WITHDRAWAL',
                    'amount': amount,
                    'status': 'FAILED_INSUFFICIENT_FUNDS',
                    'flags': fraud_flags
                })
                return False, "Insufficient balance.", fraud_flags

            if account.get_daily_spent() + amount > account.daily_limit:
                account.history.append({
                    'timestamp': time.time(),
                    'type': 'WITHDRAWAL',
                    'amount': amount,
                    'status': 'FAILED_DAILY_LIMIT',
                    'flags': fraud_flags
                })
                return False, "Daily transaction limit exceeded.", fraud_flags

            # Deduct balance
            account.balance -= amount
            account.history.append({
                'timestamp': time.time(),
                'type': 'WITHDRAWAL',
                'amount': amount,
                'status': 'SUCCESS',
                'flags': fraud_flags
            })
            
            msg = "Withdrawal successful." if not fraud_flags else "Withdrawal successful (Flagged for review)."
            return True, msg, fraud_flags

    def transfer(self, sender_id, receiver_id, pin, amount):
        if amount <= 0:
            return False, "Amount must be positive.", []
        if sender_id == receiver_id:
            return False, "Cannot transfer money to the same account.", []

        with self.system_lock:
            sender = self.accounts.get(sender_id)
            receiver = self.accounts.get(receiver_id)

        if not sender:
            return False, "Sender account not found.", []
        if not receiver:
            return False, "Receiver account not found.", []

        # Acquire locks safely in a fixed order to prevent deadlocks
        primary_lock, secondary_lock = (sender, receiver) if sender_id < receiver_id else (receiver, sender)

        with primary_lock.lock:
            with secondary_lock.lock:
                pin_ok = sender.verify_pin(pin)
                fraud_flags = self._detect_fraud(sender, amount, pin_ok, 'TRANSFER_OUT')

                if not pin_ok:
                    sender.history.append({
                        'timestamp': time.time(),
                        'type': 'TRANSFER_OUT',
                        'amount': amount,
                        'status': 'FAILED_PIN',
                        'flags': fraud_flags
                    })
                    return False, "Invalid PIN or account locked.", fraud_flags

                if sender.balance < amount:
                    sender.history.append({
                        'timestamp': time.time(),
                        'type': 'TRANSFER_OUT',
                        'amount': amount,
                        'status': 'FAILED_INSUFFICIENT_FUNDS',
                        'flags': fraud_flags
                    })
                    return False, "Insufficient balance.", fraud_flags

                if sender.get_daily_spent() + amount > sender.daily_limit:
                    sender.history.append({
                        'timestamp': time.time(),
                        'type': 'TRANSFER_OUT',
                        'amount': amount,
                        'status': 'FAILED_DAILY_LIMIT',
                        'flags': fraud_flags
                    })
                    return False, "Daily transaction limit exceeded.", fraud_flags

                # Duplicate transaction detection helper
                now = time.time()
                for tx in reversed(sender.history):
                    if now - tx['timestamp'] > 60:  # Look back 1 minute
                        break
                    if tx['type'] == 'TRANSFER_OUT' and tx['amount'] == amount and tx['status'] == 'SUCCESS':
                        fraud_flags.append("POSSIBLE_DUPLICATE_TRANSACTION")
                        break

                sender.balance -= amount
                receiver.balance += amount

                timestamp = time.time()
                sender.history.append({
                    'timestamp': timestamp,
                    'type': 'TRANSFER_OUT',
                    'amount': amount,
                    'to': receiver_id,
                    'status': 'SUCCESS',
                    'flags': fraud_flags
                })
                receiver.history.append({
                    'timestamp': timestamp,
                    'type': 'TRANSFER_IN',
                    'amount': amount,
                    'from': sender_id,
                    'status': 'SUCCESS',
                    'flags': []
                })

                msg = "Transfer successful." if not fraud_flags else "Transfer successful (Flagged for review)."
                return True, msg, fraud_flags

    def verify_balance(self, account_id):
        with self.system_lock:
            account = self.accounts.get(account_id)
        if not account:
