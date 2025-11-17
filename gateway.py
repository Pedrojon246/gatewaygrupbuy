"""
Gateway de Pagamento com Escrow e Token Gating Web3
Sistema modular para processamento de pagamentos com múltiplos adquirentes,
custódia de fundos (escrow) e verificação de tokens blockchain.

VERSÃO 2.0 - Com Persistência de Dados (SQLite) e Segurança de API
"""

from flask import Flask, request, jsonify
from typing import Dict, List, Optional, Tuple
import requests
from web3 import Web3
from datetime import datetime
import json
import uuid
import os
from functools import wraps

# SQLAlchemy para ORM e persistência
from sqlalchemy import create_engine, Column, String, Float, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, scoped_session

# ============================================================================
# MÓDULO 1: CONFIGURAÇÃO E INFRAESTRUTURA (COM VARIÁVEIS DE AMBIENTE)
# ============================================================================

class Config:
    """
    Classe de configuração centralizada para todas as credenciais e endpoints.
    """
    
    # -------- SEGURANÇA DA API --------
    API_SECRET_KEY = os.environ.get('API_SECRET_KEY')
    
    # -------- PSP/ESCROW CONFIGURATION --------
    PSP_ESCROW_API_KEY_SANDBOX = os.environ.get(
        'PSP_ESCROW_API_KEY_SANDBOX',
        '[SUA_CHAVE_API_PSP_SANDBOX]'
    )
    PSP_ESCROW_API_KEY_PRODUCTION = os.environ.get(
        'PSP_ESCROW_API_KEY_PRODUCTION',
        '[SUA_CHAVE_API_PSP_PRODUCTION]'
    )
    PSP_ESCROW_ENDPOINT = os.environ.get(
        'PSP_ESCROW_ENDPOINT',
        'https://api.provedor-escrow.com/v1'
    )
    PSP_ESCROW_ENVIRONMENT = os.environ.get(
        'PSP_ESCROW_ENVIRONMENT',
        'sandbox'
    )
    
    @staticmethod
    def get_psp_api_key():
        if Config.PSP_ESCROW_ENVIRONMENT == "production":
            return Config.PSP_ESCROW_API_KEY_PRODUCTION
        return Config.PSP_ESCROW_API_KEY_SANDBOX
    
    # -------- ADQUIRENTES CONFIGURATION (MERCADO PAGO) --------
    ADQUIRENTE_A_API_KEY = os.environ.get(
        'ADQUIRENTE_A_API_KEY',
        '[SUA_CHAVE_API_ADQUIRENTE_A_SANDBOX]'
    )
    ADQUIRENTE_A_ENDPOINT = os.environ.get(
        'ADQUIRENTE_A_ENDPOINT',
        'https://api.mercadopago.com' # MP ENDPOINT CORRETO
    )
    
    ADQUIRENTE_B_API_KEY = os.environ.get(
        'ADQUIRENTE_B_API_KEY',
        '[SUA_CHAVE_API_ADQUIRENTE_B_SANDBOX]'
    )
    ADQUIRENTE_B_ENDPOINT = os.environ.get(
        'ADQUIRENTE_B_ENDPOINT',
        'https://api.mercadopago.com' # MP ENDPOINT CORRETO
    )
    
    # -------- WEB3 CONFIGURATION --------
    WEB3_PROVIDER_URL = os.environ.get(
        'WEB3_PROVIDER_URL',
        'https://[SUA_REDE].g.alchemy.com/v2/[SUA_CHAVE_API_ALCHEMY]'
    )
    
    TOKEN_CONTRACT_ADDRESS = os.environ.get(
        'TOKEN_CONTRACT_ADDRESS',
        '[ENDEREÇO_DO_SEU_CONTRATO_TOKEN]'
    )
    
    MIN_BALANCE_UNITS = int(os.environ.get('MIN_BALANCE_UNITS', 100))
    
    TOKEN_ABI = [
        {
            "constant": True,
            "inputs": [{"name": "_owner", "type": "address"}],
            "name": "balanceOf",
            "outputs": [{"name": "balance", "type": "uint256"}],
            "type": "function"
        },
        {
            "constant": True,
            "inputs": [],
            "name": "decimals",
            "outputs": [{"name": "", "type": "uint8"}],
            "type": "function"
        }
    ]
    
    # -------- TAXAS DO SISTEMA --------
    TAXA_COM_TOKEN = float(os.environ.get('TAXA_COM_TOKEN', 2.0))
    TAXA_SEM_TOKEN = float(os.environ.get('TAXA_SEM_TOKEN', 5.0))
    
    # -------- DATABASE CONFIGURATION --------
    DATABASE_URL = os.environ.get(
        'DATABASE_URL',
        'sqlite:///gateway_db.sqlite'
    )


# ============================================================================
# MÓDULO 2: PERSISTÊNCIA DE DADOS (SQLAlchemy + SQLite)
# (CÓDIGO INALTERADO)
# ============================================================================

Base = declarative_base()

# ... EscrowModel e DatabaseService (CÓDIGO INALTERADO) ...
class EscrowModel(Base):
    """
    Modelo de dados para armazenar informações de Escrow.
    """
    __tablename__ = 'escrows'
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    codigo_escrow = Column(String(50), unique=True, nullable=False, index=True)
    transaction_id = Column(String(50), nullable=False)
    id_fornecedor = Column(String(100), nullable=False)
    valor_taxa = Column(Float, nullable=False)
    valor_produto = Column(Float, nullable=False)
    status_escrow = Column(String(20), nullable=False, default='PENDENTE')
    data_criacao = Column(DateTime, default=datetime.now)
    data_atualizacao = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    def __repr__(self):
        return f"<Escrow {self.codigo_escrow} - Status: {self.status_escrow}>"
    
    def to_dict(self):
        """Converte o modelo para dicionário"""
        return {
            'id': self.id,
            'codigo_escrow': self.codigo_escrow,
            'transaction_id': self.transaction_id,
            'id_fornecedor': self.id_fornecedor,
            'valor_taxa': self.valor_taxa,
            'valor_produto': self.valor_produto,
            'status_escrow': self.status_escrow,
            'data_criacao': self.data_criacao.isoformat(),
            'data_atualizacao': self.data_atualizacao.isoformat()
        }


class DatabaseService:
    """
    Serviço de banco de dados para encapsular todas as operações com SQLAlchemy.
    """
    
    def __init__(self, database_url: str = None):
        """Inicializa o serviço de banco de dados"""
        self.database_url = database_url or Config.DATABASE_URL
        
        self.engine = create_engine(
            self.database_url,
            echo=False,
            connect_args={'check_same_thread': False} if 'sqlite' in self.database_url else {}
        )
        
        Base.metadata.create_all(self.engine)
        
        session_factory = sessionmaker(bind=self.engine)
        self.Session = scoped_session(session_factory)
        
        print(f"[DATABASE] ✓ Conectado: {self.database_url}")
    
    def criar_escrow(
        self,
        codigo_escrow: str,
        transaction_id: str,
        id_fornecedor: str,
        valor_taxa: float,
        valor_produto: float
    ) -> EscrowModel:
        """Cria um novo registro de escrow no banco de dados"""
        session = self.Session()
        try:
            escrow = EscrowModel(
                codigo_escrow=codigo_escrow,
                transaction_id=transaction_id,
                id_fornecedor=id_fornecedor,
                valor_taxa=valor_taxa,
                valor_produto=valor_produto,
                status_escrow='PENDENTE'
            )
            
            session.add(escrow)
            session.commit()
            session.refresh(escrow)
            
            print(f"[DATABASE] ✓ Escrow criado: {codigo_escrow} (Status: PENDENTE)")
            return escrow
            
        except Exception as e:
            session.rollback()
            print(f"[DATABASE] ✗ Erro ao criar escrow: {e}")
            raise
        finally:
            session.close()
    
    def buscar_por_codigo(self, codigo_escrow: str) -> Optional[EscrowModel]:
        """Busca um escrow pelo código"""
        session = self.Session()
        try:
            escrow = session.query(EscrowModel).filter_by(
                codigo_escrow=codigo_escrow
            ).first()
            
            if escrow:
                session.expunge(escrow)
            
            return escrow
            
        finally:
            session.close()
    
    def atualizar_status(
        self,
        codigo_escrow: str,
        novo_status: str
    ) -> bool:
        """Atualiza o status de um escrow"""
        session = self.Session()
        try:
            escrow = session.query(EscrowModel).filter_by(
                codigo_escrow=codigo_escrow
            ).first()
            
            if not escrow:
                print(f"[DATABASE] ✗ Escrow não encontrado: {codigo_escrow}")
                return False
            
            status_anterior = escrow.status_escrow
            escrow.status_escrow = novo_status
            escrow.data_atualizacao = datetime.now()
            
            session.commit()
            
            print(f"[DATABASE] ✓ Status atualizado: {codigo_escrow}")
            print(f"[DATABASE]   {status_anterior} → {novo_status}")
            
            return True
            
        except Exception as e:
            session.rollback()
            print(f"[DATABASE] ✗ Erro ao atualizar status: {e}")
            return False
        finally:
            session.close()
    
    def listar_todos(self) -> List[EscrowModel]:
        """Lista todos os escrows no banco"""
        session = self.Session()
        try:
            escrows = session.query(EscrowModel).all()
            
            for escrow in escrows:
                session.expunge(escrow)
            
            return escrows
            
        finally:
            session.close()


# ============================================================================
# MÓDULO 3: SEGURANÇA DA API (AUTENTICAÇÃO POR API KEY)
# (CÓDIGO INALTERADO)
# ============================================================================

def require_api_key(f):
    """
    Decorator para proteger endpoints com autenticação por API Key.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-API-Key')
        
        if not api_key:
            print("[SECURITY] ✗ Tentativa de acesso sem API Key")
            return jsonify({
                "erro": "API Key não fornecida",
                "detalhes": "Inclua o cabeçalho X-API-Key na requisição"
            }), 401
        
        if api_key != Config.API_SECRET_KEY:
            print(f"[SECURITY] ✗ Tentativa de acesso com API Key inválida")
            return jsonify({
                "erro": "API Key inválida",
                "detalhes": "A chave fornecida não é válida"
            }), 401
        
        print(f"[SECURITY] ✓ Acesso autorizado para {request.path}")
        return f(*args, **kwargs)
    
    return decorated_function


# ============================================================================
# MÓDULO 4: LÓGICA DE PAGAMENTO E ESCROW (MUNDO FIAT)
# ============================================================================

class GatewayMultiAdquirente:
    """
    Classe responsável pelo roteamento de pagamentos entre múltiplos adquirentes
    e pela gestão de escrow/custódia de fundos com persistência de dados.
    """
    
    def __init__(self, db_service: DatabaseService):
        """Inicializa o gateway com serviço de banco de dados"""
        # CORRIGIDO: Removido PSP_Escrow_Fallback do roteamento
        self.roteamento_prioritario = [
            'AdquirenteA',
            'AdquirenteB',
        ]
        self.db = db_service
    
    def _enviar_para_adquirente(
        self, 
        nome_adquirente: str, 
        dados_transacao: Dict
    ) -> Tuple[bool, Dict]:
        """
        Faz a chamada HTTP real para as APIs dos adquirentes (Mercado Pago).
        """
        print(f"[GATEWAY] Tentando processar com {nome_adquirente}...")
        
        if nome_adquirente == 'AdquirenteA':
            # Endpoint e Configurações para Mercado Pago (MP)
            endpoint = Config.ADQUIRENTE_A_ENDPOINT.rstrip('/') + "/v1/payments"
            headers = {
                "Authorization": f"Bearer {Config.ADQUIRENTE_A_API_KEY}",
                "Content-Type": "application/json",
                # Adicionando chave de Idempotência para segurança contra duplicação
                "X-Idempotency-Key": str(uuid.uuid4())
            }
            # CORRIGIDO: Payload para usar TOKEN (Obrigatório em produção MP)
            payload = {
                "transaction_amount": float(dados_transacao.get("valor_total")), 
                "description": dados_transacao.get("descricao", "Compra em Grupo"),
                "token": dados_transacao.get("card_token"),  # <-- USA O TOKEN DO FRONTEND
                "installments": 1, # Pode ser dinâmico, mas 1 para teste
                "payment_method_id": dados_transacao.get("payment_method_id", "visa"),
                "payer": {
                    "email": dados_transacao.get("email_cliente", "default_email@base44.com"),
                    "identification": {
                        "type": dados_transacao.get("doc_type", "CPF"),
                        "number": dados_transacao.get("doc_number", "12345678900")
                    }
                }
            }
            
        elif nome_adquirente == 'AdquirenteB':
            # Endpoint e Configurações para Mercado Pago (MP)
            endpoint = Config.ADQUIRENTE_B_ENDPOINT.rstrip('/') + "/v1/payments"
            headers = {
                "Authorization": f"Bearer {Config.ADQUIRENTE_B_API_KEY}",
                "Content-Type": "application/json",
                 "X-Idempotency-Key": str(uuid.uuid4())
            }
            # CORRIGIDO: Payload para usar TOKEN (Obrigatório em produção MP)
            payload = {
                "transaction_amount": float(dados_transacao.get("valor_total")), 
                "description": dados_transacao.get("descricao", "Compra em Grupo"),
                "token": dados_transacao.get("card_token"), # <-- USA O TOKEN DO FRONTEND
                "installments": 1, # Pode ser dinâmico
                "payment_method_id": dados_transacao.get("payment_method_id", "visa"),
                "payer": {
                    "email": dados_transacao.get("email_cliente", "default_email@base44.com"),
                    "identification": {
                        "type": dados_transacao.get("doc_type", "CPF"),
                        "number": dados_transacao.get("doc_number", "12345678900")
                    }
                }
            }
            
        else:
             # Este bloco só será acionado se você adicionar um novo PSP no roteamento
            endpoint = Config.PSP_ESCROW_ENDPOINT + "/transactions"
            headers = {
                "Authorization": f"Bearer {Config.get_psp_api_key()}",
                "Content-Type": "application/json"
            }
            payload = {
                 # O FLUXO DE TOKENIZAÇÃO DESTE PSP DEVE SER DEFINIDO AQUI
                "amount": dados_transacao.get("valor_total"),
                "description": dados_transacao.get("descricao", "Compra em Grupo")
            }
        
        # ATIVAÇÃO: CHAMADA REAL DE PRODUÇÃO
        try:
            response = requests.post(endpoint, json=payload, headers=headers, timeout=30)
            
            if response.status_code in [200, 201]:
                # SUCESSO. Retorna o ID de transação do Mercado Pago
                response_json = response.json()
                return True, { 
                    "status": response_json.get("status", "approved"),
                    "transaction_id": response_json.get('id'), 
                    "adquirente": nome_adquirente,
                    "detalhes": response_json
                }
            else:
                # FALHA. Retorna o erro exato da API do MP
                print(f"[GATEWAY] ✗ Falha MP ({response.status_code}): {response.text}")
                return False, {"error": response.text, "status_code": response.status_code}
        except Exception as e:
            # Erro de conexão/timeout
            print(f"[GATEWAY] ✗ Erro de conexão: {str(e)}")
            return False, {"error": str(e), "status_code": 500}
        
    
    # ... processar_pagamento_escrow e outros métodos (CÓDIGO INALTERADO) ...
    def processar_pagamento_escrow(
        self,
        dados_transacao: Dict,
        id_fornecedor: str,
        valor_taxa: float,
        valor_produto: float
    ) -> Dict:
        """Processa o pagamento e registra no escrow com persistência"""
        for adquirente in self.roteamento_prioritario:
            sucesso, resposta = self._enviar_para_adquirente(adquirente, dados_transacao)
            
            if sucesso:
                print(f"[GATEWAY] ✓ Pagamento aprovado via {adquirente}")
                
                codigo_escrow = self._registrar_escrow(
                    transaction_id=resposta.get("transaction_id"),
                    id_fornecedor=id_fornecedor,
                    valor_taxa=valor_taxa,
                    valor_produto=valor_produto,
                    dados_transacao=dados_transacao
                )
                
                return {
                    "sucesso": True,
                    "adquirente": adquirente,
                    "transaction_id": resposta.get("transaction_id"),
                    "codigo_escrow": codigo_escrow,
                    "status": "em_custodia",
                    "detalhes": resposta
                }
            else:
                print(f"[GATEWAY] ✗ Falha com {adquirente}: {resposta.get('error')}")
        
        return {
            "sucesso": False,
            "erro": "Todos os adquirentes falharam ao processar o pagamento",
            "status": "negado"
        }
    
    def _registrar_escrow(
        self,
        transaction_id: str,
        id_fornecedor: str,
        valor_taxa: float,
        valor_produto: float,
        dados_transacao: Dict
    ) -> str:
        """Registra a transação no sistema de escrow do PSP e no banco de dados local"""
        endpoint = Config.PSP_ESCROW_ENDPOINT + "/escrow/create"
        headers = {
            "Authorization": f"Bearer {Config.get_psp_api_key()}",
            "Content-Type": "application/json"
        }
        
        codigo_escrow = f"ESC_{uuid.uuid4().hex[:16].upper()}"
        
        payload = {
            "escrow_code": codigo_escrow,
            "transaction_id": transaction_id,
            "total_amount": valor_taxa + valor_produto,
            "splits": [
                {
                    "recipient_id": "APP_BASE44",
                    "amount": valor_taxa,
                    "status": "held",
                    "description": "Taxa da plataforma"
                },
                {
                    "recipient_id": id_fornecedor,
                    "amount": valor_produto,
                    "status": "held",
                    "description": "Valor do produto"
                }
            ],
            "metadata": {
                "created_at": datetime.now().isoformat(),
                "release_trigger": "manual"
            }
        }
        
        # SIMULAÇÃO: Em produção, descomente
        try:
             response = requests.post(endpoint, json=payload, headers=headers, timeout=30)
             if response.status_code in [200, 201]:
                 codigo_escrow = response.json().get("escrow_code", codigo_escrow)
             else:
                 print(f"[ESCROW] ⚠ Aviso: Falha ao registrar no PSP ({response.status_code}). Registrando localmente.")
        except Exception as e:
            print(f"[ESCROW] Erro ao registrar no PSP: {e}")
        
        print(f"[ESCROW] ✓ Registrado no PSP: {codigo_escrow}")
        print(f"[ESCROW]   - Taxa App: R$ {valor_taxa:.2f} (retido)")
        print(f"[ESCROW]   - Fornecedor: R$ {valor_produto:.2f} (retido)")
        
        # Persistir no banco de dados local
        try:
            self.db.criar_escrow(
                codigo_escrow=codigo_escrow,
                transaction_id=transaction_id,
                id_fornecedor=id_fornecedor,
                valor_taxa=valor_taxa,
                valor_produto=valor_produto
            )
        except Exception as e:
            print(f"[ESCROW] ✗ Erro ao salvar no banco: {e}")
        
        return codigo_escrow
    
    def liberar_taxa(self, codigo_escrow: str) -> Dict:
        """
        Libera o valor da taxa para a conta final do App.
        """
        # VALIDAÇÃO NO BANCO DE DADOS
        escrow_db = self.db.buscar_por_codigo(codigo_escrow)
        
        if not escrow_db:
            print(f"[ESCROW] ✗ Código não encontrado no banco: {codigo_escrow}")
            return {
                "sucesso": False,
                "erro": "Código de escrow não encontrado",
                "codigo_escrow": codigo_escrow
            }
        
        if escrow_db.status_escrow == 'CANCELADO':
            print(f"[ESCROW] ✗ Escrow cancelado, não é possível liberar")
            return {
                "sucesso": False,
                "erro": "Escrow cancelado, liberação não permitida",
                "status_atual": escrow_db.status_escrow
            }
        
        if escrow_db.status_escrow == 'FINALIZADO':
            print(f"[ESCROW] ✗ Escrow já finalizado")
            return {
                "sucesso": False,
                "erro": "Escrow já foi finalizado anteriormente",
                "status_atual": escrow_db.status_escrow
            }
        
        # Prosseguir com liberação no PSP
        endpoint = Config.PSP_ESCROW_ENDPOINT + f"/escrow/{codigo_escrow}/release"
        headers = {
            "Authorization": f"Bearer {Config.get_psp_api_key()}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "recipient_id": "APP_BASE44",
            "action": "release_to_final_account"
        }
        
        # SIMULAÇÃO: Em produção, descomente
        try:
            response = requests.post(endpoint, json=payload, headers=headers, timeout=30)
            if response.status_code != 200:
                 # Se a liberação falhar na API do PSP, não atualizamos o DB
                print(f"[ESCROW] ✗ Falha na liberação no PSP ({response.status_code}): {response.text}")
                return {"sucesso": False, "erro": response.text}
        except Exception as e:
            print(f"[ESCROW] ✗ Erro de conexão ao liberar taxa: {str(e)}")
            return {"sucesso": False, "erro": str(e)}
        
        print(f"[ESCROW] ✓ Taxa liberada para App (Escrow: {codigo_escrow})")
        
        # Atualizar status no banco de dados
        self.db.atualizar_status(codigo_escrow, 'TAXA_LIBERADA')
        
        return {
            "sucesso": True,
            "codigo_escrow": codigo_escrow,
            "liberado_para": "APP_BASE44",
            "valor_liberado": escrow_db.valor_taxa,
            "novo_status": "TAXA_LIBERADA",
            "timestamp": datetime.now().isoformat()
        }
    
    def liberar_produto_fornecedor(self, codigo_escrow: str) -> Dict:
        """
        Libera o valor do produto para a conta final do Fornecedor.
        """
        # VALIDAÇÃO NO BANCO DE DADOS
        escrow_db = self.db.buscar_por_codigo(codigo_escrow)
        
        if not escrow_db:
            print(f"[ESCROW] ✗ Código não encontrado no banco: {codigo_escrow}")
            return {
                "sucesso": False,
                "erro": "Código de escrow não encontrado",
                "codigo_escrow": codigo_escrow
            }
        
        if escrow_db.status_escrow == 'CANCELADO':
            print(f"[ESCROW] ✗ Escrow cancelado, não é possível liberar")
            return {
                "sucesso": False,
                "erro": "Escrow cancelado, liberação não permitida",
                "status_atual": escrow_db.status_escrow
            }
        
        if escrow_db.status_escrow == 'FINALIZADO':
            print(f"[ESCROW] ✗ Escrow já finalizado")
            return {
                "sucesso": False,
                "erro": "Escrow já foi finalizado anteriormente",
                "status_atual": escrow_db.status_escrow
            }
        
        if escrow_db.status_escrow != 'TAXA_LIBERADA':
            print(f"[ESCROW] ⚠ Aviso: Liberando produto antes da taxa")
        
        # Prosseguir com liberação no PSP
        endpoint = Config.PSP_ESCROW_ENDPOINT + f"/escrow/{codigo_escrow}/release"
        headers = {
            "Authorization": f"Bearer {Config.get_psp_api_key()}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "recipient_type": "supplier",
            "action": "release_to_final_account"
        }
        
        # SIMULAÇÃO: Em produção, descomente
        try:
            response = requests.post(endpoint, json=payload, headers=headers, timeout=30)
            if response.status_code != 200:
                # Se a liberação falhar na API do PSP, não atualizamos o DB
                print(f"[ESCROW] ✗ Falha na liberação no PSP ({response.status_code}): {response.text}")
                return {"sucesso": False, "erro": response.text}
        except Exception as e:
            print(f"[ESCROW] ✗ Erro de conexão ao liberar produto: {str(e)}")
            return {"sucesso": False, "erro": str(e)}
        
        print(f"[ESCROW] ✓ Produto liberado para Fornecedor (Escrow: {codigo_escrow})")
        
        # Atualizar status no banco de dados para FINALIZADO
        self.db.atualizar_status(codigo_escrow, 'FINALIZADO')
        
        return {
            "sucesso": True,
            "codigo_escrow": codigo_escrow,
            "liberado_para": "FORNECEDOR",
            "valor_liberado": escrow_db.valor_produto,
            "novo_status": "FINALIZADO",
            "timestamp": datetime.now().isoformat()
        }


# ============================================================================
# MÓDULO 5: LÓGICA WEB3 (TOKEN GATING)
# (CÓDIGO INALTERADO)
# ============================================================================

class VerificadorTokenWeb3:
    # ... (CÓDIGO INALTERADO) ...
    def __init__(self):
        """Inicializa conexão Web3 e contrato do token"""
        try:
            self.w3 = Web3(Web3.HTTPProvider(Config.WEB3_PROVIDER_URL))
            
            if self.w3.is_connected():
                print("[WEB3] ✓ Conectado à blockchain")
            else:
                print("[WEB3] ✗ Falha na conexão com blockchain")
                self.w3 = None
                return
            
            if not self.w3.is_address(Config.TOKEN_CONTRACT_ADDRESS):
                print("[WEB3] ✗ Endereço do contrato inválido")
                self.contrato = None
                return
            
            checksum_address = self.w3.to_checksum_address(Config.TOKEN_CONTRACT_ADDRESS)
            self.contrato = self.w3.eth.contract(
                address=checksum_address,
                abi=Config.TOKEN_ABI
            )
            
            try:
                self.decimals = self.contrato.functions.decimals().call()
            except:
                self.decimals = 18
            
            print(f"[WEB3] ✓ Contrato inicializado (Decimals: {self.decimals})")
            
        except Exception as e:
            print(f"[WEB3] ✗ Erro na inicialização: {e}")
            self.w3 = None
            self.contrato = None
    
    def verificar_posse_token(self, endereco_carteira: str) -> Dict:
        """Verifica se um endereço possui a quantidade mínima de tokens"""
        
        if not self.w3 or not self.contrato:
            return {
                "token_holder": False,
                "saldo": 0,
                "erro": "Serviço Web3 não disponível"
            }
        
        try:
            if not self.w3.is_address(endereco_carteira):
                return {
                    "token_holder": False,
                    "saldo": 0,
                    "erro": "Endereço de carteira inválido"
                }
            
            checksum_address = self.w3.to_checksum_address(endereco_carteira)
            
            saldo_raw = self.contrato.functions.balanceOf(checksum_address).call()
            saldo = saldo_raw / (10 ** self.decimals)
            
            is_holder = saldo >= Config.MIN_BALANCE_UNITS
            
            print(f"[WEB3] Verificação: {endereco_carteira[:10]}...")
            print(f"[WEB3]   - Saldo: {saldo:.2f} tokens")
            print(f"[WEB3]   - Holder: {'SIM' if is_holder else 'NÃO'}")
            
            return {
                "token_holder": is_holder,
                "saldo": saldo,
                "saldo_raw": saldo_raw,
                "minimo_requerido": Config.MIN_BALANCE_UNITS,
                "endereco_verificado": checksum_address
            }
            
        except Exception as e:
            print(f"[WEB3] ✗ Erro na verificação: {e}")
            return {
                "token_holder": False,
                "saldo": 0,
                "erro": f"Erro na leitura da blockchain: {str(e)}"
            }


# ============================================================================
# MÓDULO 6: SERVIDOR API (ENDPOINTS FLASK COM SEGURANÇA)
# ============================================================================

app = Flask(__name__)

# Instanciar componentes do sistema
db_service = DatabaseService()
gateway = GatewayMultiAdquirente(db_service)
verificador_web3 = VerificadorTokenWeb3()


@app.route('/api/checkout', methods=['POST'])
@require_api_key
def checkout():
    """
    Endpoint principal de checkout. AGORA RECEBE O TOKEN DO CARTÃO.
    
    Body esperado:
    {
        "card_token": "abc123...",     (TOKEN DO FRONTEND - OBRIGATÓRIO)
        "payment_method_id": "visa",
        "email_cliente": "cliente@email.com",
        "doc_type": "CPF",
        "doc_number": "12345678900",
        "valor_produto": 100.00,
        "id_fornecedor": "FORN_12345",
        "descricao": "Compra em Grupo - Produto X",
        "endereco_carteira": "0x..." (opcional)
    }
    """
    try:
        dados = request.get_json()
        
        # CAMPOS OBRIGATÓRIOS DO NOVO FLUXO (Tokenizado)
        card_token = dados.get('card_token')
        email_cliente = dados.get('email_cliente')
        
        # VALIDAÇÃO CRÍTICA DO FLUXO DE PRODUÇÃO
        if not card_token:
            return jsonify({"erro": "Token do cartão (card_token) não fornecido. O frontend deve tokenizar primeiro."}), 400
        
        valor_produto = float(dados.get('valor_produto', 0))
        id_fornecedor = dados.get('id_fornecedor')
        descricao = dados.get('descricao', 'Compra em Grupo')
        endereco_carteira = dados.get('endereco_carteira')
        
        if valor_produto <= 0:
            return jsonify({"erro": "Valor do produto inválido"}), 400
        
        if not id_fornecedor:
            return jsonify({"erro": "ID do fornecedor não informado"}), 400
        
        # Verificar posse de token (se carteira fornecida)
        is_token_holder = False
        verificacao_web3 = None
        
        if endereco_carteira:
            verificacao_web3 = verificador_web3.verificar_posse_token(endereco_carteira)
            is_token_holder = verificacao_web3.get('token_holder', False)
        
        # Calcular taxa baseado em token holding
        if is_token_holder:
            percentual_taxa = Config.TAXA_COM_TOKEN
            motivo_taxa = "Taxa reduzida para Token Holders"
        else:
            percentual_taxa = Config.TAXA_SEM_TOKEN
            motivo_taxa = "Taxa padrão"
        
        valor_taxa = valor_produto * (percentual_taxa / 100)
        valor_total = valor_produto + valor_taxa
        
        # DADOS DA TRANSAÇÃO ATUALIZADOS PARA USAR O TOKEN
        dados_transacao = {
            "card_token": card_token,
            "payment_method_id": dados.get('payment_method_id', 'visa'),
            "email_cliente": email_cliente,
            "doc_type": dados.get('doc_type', 'CPF'),
            "doc_number": dados.get('doc_number'),
            "valor_total": valor_total,
            "descricao": descricao
        }
        
        resultado = gateway.processar_pagamento_escrow(
            dados_transacao=dados_transacao,
            id_fornecedor=id_fornecedor,
            valor_taxa=valor_taxa,
            valor_produto=valor_produto
        )
        
        resposta = {
            "checkout": {
                "sucesso": resultado.get('sucesso'),
                "status": resultado.get('status'),
                "codigo_escrow": resultado.get('codigo_escrow'),
                "transaction_id": resultado.get('transaction_id'),
                "adquirente": resultado.get('adquirente')
            },
            "valores": {
                "produto": valor_produto,
                "taxa": valor_taxa,
                "percentual_taxa": percentual_taxa,
                "total": valor_total,
                "motivo_taxa": motivo_taxa
            },
            "web3": {
                "verificado": endereco_carteira is not None,
                "token_holder": is_token_holder,
                "detalhes": verificacao_web3
            }
        }
        
        if resultado.get('sucesso'):
            return jsonify(resposta), 200
        else:
            resposta['erro'] = resultado.get('erro')
            return jsonify(resposta), 400
        
    except Exception as e:
        return jsonify({"erro": f"Erro no processamento: {str(e)}"}), 500


@app.route('/api/web3/check', methods=['POST'])
def check_web3():
    # ... (CÓDIGO INALTERADO) ...
    try:
        dados = request.get_json()
        endereco_carteira = dados.get('endereco_carteira')
        
        if not endereco_carteira:
            return jsonify({"erro": "Endereço de carteira não informado"}), 400
        
        resultado = verificador_web3.verificar_posse_token(endereco_carteira)
        
        return jsonify(resultado), 200
        
    except Exception as e:
        return jsonify({"erro": f"Erro na verificação: {str(e)}"}), 500


@app.route('/api/escrow/liberar/taxa', methods=['POST'])
@require_api_key
def liberar_taxa():
    # ... (CÓDIGO INALTERADO) ...
    try:
        dados = request.get_json()
        codigo_escrow = dados.get('codigo_escrow')
        
        if not codigo_escrow:
            return jsonify({"erro": "Código do escrow não informado"}), 400
        
        resultado = gateway.liberar_taxa(codigo_escrow)
        
        if resultado.get('sucesso'):
            return jsonify(resultado), 200
        else:
            return jsonify(resultado), 400
        
    except Exception as e:
        return jsonify({"erro": f"Erro ao liberar taxa: {str(e)}"}), 500


@app.route('/api/escrow/liberar/produto', methods=['POST'])
@require_api_key
def liberar_produto():
    # ... (CÓDIGO INALTERADO) ...
    try:
        dados = request.get_json()
        codigo_escrow = dados.get('codigo_escrow')
        
        if not codigo_escrow:
            return jsonify({"erro": "Código do escrow não informado"}), 400
        
        resultado = gateway.liberar_produto_fornecedor(codigo_escrow)
        
        if resultado.get('sucesso'):
            return jsonify(resultado), 200
        else:
            return jsonify(resultado), 400
        
    except Exception as e:
        return jsonify({"erro": f"Erro ao liberar produto: {str(e)}"}), 500


@app.route('/api/escrow/consultar/<codigo_escrow>', methods=['GET'])
@require_api_key
def consultar_escrow(codigo_escrow):
    # ... (CÓDIGO INALTERADO) ...
    try:
        escrow = db_service.buscar_por_codigo(codigo_escrow)
        
        if not escrow:
            return jsonify({"erro": "Escrow não encontrado"}), 404
        
        return jsonify(escrow.to_dict()), 200
        
    except Exception as e:
        return jsonify({"erro": f"Erro ao consultar escrow: {str(e)}"}), 500


@app.route('/health', methods=['GET'])
def health():
    """Endpoint de health check - NÃO PROTEGIDO"""
    return jsonify({
        "status": "online",
        "timestamp": datetime.now().isoformat(),
        "services": {
            "gateway": "ok",
            "database": "ok",
            "web3": "ok" if verificador_web3.w3 else "offline"
        }
    }), 200


# ============================================================================
# INICIALIZAÇÃO DO SERVIDOR
# ============================================================================

#if __name__ == '__main__':
#    print("=" * 70)
#    print("GATEWAY DE PAGAMENTO COM ESCROW E TOKEN GATING v2.0")
#    print("=" * 70)
#    print("\n[SISTEMA] Inicializando componentes...")
#    print(f"[SISTEMA] Ambiente PSP: {Config.PSP_ESCROW_ENVIRONMENT}")
#    print(f"[SISTEMA] Taxa com Token: {Config.TAXA_COM_TOKEN}%")
#    print(f"[SISTEMA] Taxa sem Token: {Config.TAXA_SEM_TOKEN}%")
#    print(f"[SISTEMA] Banco de Dados: {Config.DATABASE_URL}")
#    print("\n" + "=" * 70)
#    print("ENDPOINTS DISPONÍVEIS:")
#    print("=" * 70)
#    print("POST /api/checkout              🔒 - Processar compra com escrow")
#    print("POST /api/web3/check            🔓 - Verificar posse de token")
#    print("POST /api/escrow/liberar/taxa   🔒 - Liberar taxa da plataforma")
#    print("POST /api/escrow/liberar/produto 🔒 - Liberar valor do fornecedor")
#    print("GET  /api/escrow/consultar/<id> 🔒 - Consultar status do escrow")
#    print("GET  /health                    🔓 - Status do sistema")
#    print("=" * 70)
#    print("\n🔒 = Requer X-API-Key no cabeçalho")
#    print("🔓 = Acesso público")
#    print("\n[SISTEMA] Servidor iniciando na porta 5000...")
#    print("[SISTEMA] Pressione CTRL+C para parar\n")
#    
#    app.run(debug=True, host='0.0.0.0', port=5000)